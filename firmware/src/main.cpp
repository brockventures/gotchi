// ============================================================================
// GOTCHI V1 Edge Firmware — Seeed Studio XIAO ESP32S3 Sense (8MB Flash / 8MB PSRAM)
// Implements Epic 2 (T2.1-T2.7) & Epic 3 (T3.1):
//   - Dual-transport JSON-RPC (`USB-C Serial 115200` + `POST /api/rpc`)
//   - 16 kHz 16-bit mono PDM Mic capture into 8MB PSRAM circular pre-roll + WAV wrapper
//   - `POST /api/voice/interact` multipart WAV client + streaming SSE parser
//   - 24 kHz base64 PCM `audio_chunk` decode to MAX98357A I2S TX (`BCLK=GPIO44`)
//   - Waveshare 1.54" V2 (`SSD1681`) 200x200 e-paper sprite & partial/full refresh manager
//   - QR Soft-AP Captive Portal onboarding (`192.168.4.1`)
// ============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <driver/i2s.h>
#include "esp_camera.h"
#include "pins.h"
#include "epd_panel.h"
#include "ui_state.h"
#include "audio_hal.h"
#include "camera_hal.h"
#include "onboarding_portal.h"
#include "voice_client.h"

static Preferences prefs;
static WebServer httpServer(80);

struct GotchiConfig {
    String hub_url = "http://mirrormere.local:8080";
    // Mirrormere voice gateway. Host is a placeholder: the bench LAN address is
    // set per device with set_config (AGENTS.md §4: no RFC1918 IPs in tracked files).
    String voice_url = "http://mirrormere.local:9098/api/voice/interact";
    String node_id = "gotchi-v1-01";
    String wake_mode = "ptt";         // "ptt" | "wake_word"
    String audio_out_mode = "speaker";// "speaker" | "discord_voice" | "ble_phone"
    String skin = "zero";             // "zero" | "gotchi"
    String bearer_token = "";         // Per-device Bearer token for off-LAN / tunnel auth (T3.2)
    String wifi_ssid = "";
    String wifi_psk = "";
} cfg;

static bool constantTimeEquals(const String& a, const String& b) {
    if (a.length() != b.length()) return false;
    uint8_t diff = 0;
    for (size_t i = 0; i < a.length(); ++i) {
        diff |= (uint8_t)(a[i] ^ b[i]);
    }
    return diff == 0;
}

// PSRAM Audio Buffers (16 kHz 16-bit mono recording + 500ms circular pre-roll)
static constexpr size_t SAMPLE_RATE_REC = 16000;
static constexpr size_t PREROLL_BYTES   = SAMPLE_RATE_REC * sizeof(int16_t) / 2; // 16 KB (500ms)
static constexpr size_t MAX_WAV_BYTES   = 44 + SAMPLE_RATE_REC * sizeof(int16_t) * 15; // 15s cap
static uint8_t* psram_wav_buf = nullptr;

// Wi-Fi join at boot and push-to-talk timing.
static constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;
static constexpr uint32_t PTT_DEBOUNCE_MS = 30;
static constexpr uint32_t PTT_MAX_MS      = 15000;
static constexpr float    PTT_MIN_RMS     = 50.0f / 32768.0f;  // finishPttRecording() returns RMS normalized to [0,1]
static constexpr size_t   PTT_MIN_BYTES   = 16000;

// E-paper panel + refresh policy live in epd_panel.{h,cpp}.
EpdPanel panel;

void loadConfig() {
    prefs.begin("gotchi", true);
    cfg.hub_url        = prefs.getString("hub_url", cfg.hub_url);
    cfg.voice_url      = prefs.getString("voice_url", cfg.voice_url);
    cfg.node_id        = prefs.getString("node_id", cfg.node_id);
    cfg.wake_mode      = prefs.getString("wake_mode", cfg.wake_mode);
    cfg.audio_out_mode = prefs.getString("audio_out_mode", cfg.audio_out_mode);
    cfg.skin           = prefs.getString("skin", cfg.skin);
    cfg.bearer_token   = prefs.getString("bearer_token", "");
    cfg.wifi_ssid      = prefs.getString("wifi_ssid", "");
    cfg.wifi_psk       = prefs.getString("wifi_psk", "");
    prefs.end();
}

void saveConfig() {
    prefs.begin("gotchi", false);
    prefs.putString("hub_url", cfg.hub_url);
    prefs.putString("voice_url", cfg.voice_url);
    prefs.putString("node_id", cfg.node_id);
    prefs.putString("wake_mode", cfg.wake_mode);
    prefs.putString("audio_out_mode", cfg.audio_out_mode);
    prefs.putString("skin", cfg.skin);
    prefs.putString("bearer_token", cfg.bearer_token);
    prefs.putString("wifi_ssid", cfg.wifi_ssid);
    prefs.putString("wifi_psk", cfg.wifi_psk);
    prefs.end();
}

String handleJsonRpc(const String& jsonLine) {
    JsonDocument req;
    JsonDocument res;
    if (deserializeJson(req, jsonLine)) {
        res["ok"] = false;
        res["error"] = "invalid_json";
        String out;
        serializeJson(res, out);
        return out;
    }
    String cmd = req["cmd"] | "";
    res["cmd"] = cmd;
    res["ok"] = true;

    if (cmd == "get_config") {
        res["hub_url"] = cfg.hub_url;
        res["voice_url"] = cfg.voice_url;
        res["node_id"] = cfg.node_id;
        res["wake_mode"] = cfg.wake_mode;
        res["audio_out_mode"] = cfg.audio_out_mode;
        res["skin"] = cfg.skin;
        res["bearer_token_set"] = (cfg.bearer_token.length() > 0);
        res["wifi_ssid"] = cfg.wifi_ssid;
        res["psram_free"] = ESP.getFreePsram();
        res["fw_version"] = GOTCHI_FW_VERSION;
    } else if (cmd == "set_config") {
        if (req["hub_url"].is<const char*>()) cfg.hub_url = req["hub_url"].as<String>();
        if (req["voice_url"].is<const char*>()) cfg.voice_url = req["voice_url"].as<String>();
        if (req["node_id"].is<const char*>()) cfg.node_id = req["node_id"].as<String>();
        if (req["wake_mode"].is<const char*>()) cfg.wake_mode = req["wake_mode"].as<String>();
        if (req["audio_out_mode"].is<const char*>()) cfg.audio_out_mode = req["audio_out_mode"].as<String>();
        if (req["skin"].is<const char*>()) cfg.skin = req["skin"].as<String>();
        if (req["bearer_token"].is<const char*>()) cfg.bearer_token = req["bearer_token"].as<String>();
        saveConfig();
    } else if (cmd == "set_wifi") {
        cfg.wifi_ssid = req["ssid"] | cfg.wifi_ssid;
        cfg.wifi_psk  = req["psk"]  | cfg.wifi_psk;
        saveConfig();
    } else if (cmd == "self_test") {
        res["psram_ok"] = (psramFound() && ESP.getFreePsram() > 4000000);
        res["epd_busy_clear"] = epdWaitBusy(500);
        res["btn_top_state"] = digitalRead(PIN_BTN_TOP_PTT);
        res["btn_bot_state"] = digitalRead(PIN_BTN_BOT_MOD);
        sensor_t* s = esp_camera_sensor_get();
        res["camera_pid"] = s ? s->id.PID : 0;
    } else if (cmd == "factory_reset") {
        prefs.begin("gotchi", false);
        prefs.clear();
        prefs.end();
        res["status"] = "cleared_nvs";
    } else if (cmd == "draw_state") {
        GotchiUIState ui;
        ui.skin = req["skin"].is<const char*>() ? req["skin"].as<String>() : cfg.skin;
        ui.state = uiStateFromString(req["state"] | "idle");
        if (req["status_text"].is<const char*>()) ui.status_text = req["status_text"].as<String>();
        bool force_full = req["force_full"] | false;
        res["ok"] = panel.draw(ui, force_full);
        res["mode"] = panel.lastMode();
    } else if (cmd == "reboot") {
        ESP.restart();
    } else {
        res["ok"] = false;
        res["error"] = "unknown_command";
    }

    String out;
    serializeJson(res, out);
    return out;
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN_BTN_TOP_PTT, INPUT_PULLUP);
    pinMode(PIN_BTN_BOT_MOD, INPUT_PULLUP);
    pinMode(PIN_EPD_BUSY, INPUT);

    if (psramFound()) {
        psram_wav_buf = (uint8_t*)ps_malloc(MAX_WAV_BYTES);
    }
    loadConfig();

    // Join the configured network before the UI comes up. Unprovisioned units
    // skip this and fall through to the Soft-AP portal below.
    bool wifi_configured = cfg.wifi_ssid.length() > 0;
    bool wifi_up = false;
    if (wifi_configured) {
        WiFi.mode(WIFI_STA);
        WiFi.begin(cfg.wifi_ssid.c_str(), cfg.wifi_psk.c_str());
        uint32_t t0 = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_CONNECT_TIMEOUT_MS) {
            delay(100);
        }
        wifi_up = (WiFi.status() == WL_CONNECTED);
    }

    gotchi_audio::init();
    gotchi_camera::init();
    if (!wifi_configured) {
        gotchi_portal::startSoftApPortal(httpServer);
    }

    panel.begin();
    GotchiUIState boot_ui;
    boot_ui.skin = cfg.skin;
    if (wifi_configured && !wifi_up) {
        boot_ui.state = UiState::OFFLINE;
        boot_ui.status_text = "NO WIFI";
    }
    panel.draw(boot_ui);

    httpServer.on("/api/rpc", HTTP_POST, []() {
        if (cfg.bearer_token.length() > 0) {
            String auth = httpServer.header("Authorization");
            String expected = "Bearer " + cfg.bearer_token;
            if (!constantTimeEquals(auth, expected)) {
                httpServer.send(401, "application/json", "{\"ok\":false,\"error\":\"unauthorized\"}");
                return;
            }
        }
        String resp = handleJsonRpc(httpServer.arg("plain"));
        httpServer.send(200, "application/json", resp);
    });
    static const char* kCollectedHeaders[] = {"Authorization"};
    httpServer.collectHeaders(kCollectedHeaders, 1);
    httpServer.begin();
}

// Push-to-talk. BTN_TOP is active low; a level counts only after it has held
// for PTT_DEBOUNCE_MS. Returns true if the button is at `pressed` level.
static bool pttStable(bool pressed) {
    const int want = pressed ? LOW : HIGH;
    if (digitalRead(PIN_BTN_TOP_PTT) != want) return false;
    delay(PTT_DEBOUNCE_MS);
    return digitalRead(PIN_BTN_TOP_PTT) == want;
}

static void showIdle() {
    GotchiUIState idle_ui;
    idle_ui.skin = cfg.skin;
    panel.draw(idle_ui);
}

// Sprite callback for gotchi_voice::interact: redraw on every state change.
static void onVoiceState(const GotchiUIState& ui) {
    panel.draw(ui);
}

// One PTT turn: hold to record, release to send. Returns to idle when done.
static void runPttTurn() {
    GotchiUIState ui;
    ui.skin = cfg.skin;
    if (!gotchi_audio::beginPttRecording()) {
        ui.state = UiState::ERROR;
        ui.error_code = "mic";
        ui.status_text = "MIC ERROR";
        panel.draw(ui);
        delay(1500);
        showIdle();
        return;
    }
    // Start Core 0 DMA drain task BEFORE playing chime & drawing LISTENING so zero speech is dropped
    bool async_running = gotchi_audio::startAsyncPttTask();
    gotchi_audio::playChime("ptt_start");
    ui.state = UiState::LISTENING;
    ui.status_text = "REC 16kHz PDM MIC...";
    panel.draw(ui);

    uint32_t t0 = millis();
    while (millis() - t0 < PTT_MAX_MS) {
        if (pttStable(false)) break;
        if (!async_running) gotchi_audio::pollPttRecording();
        httpServer.handleClient();
        delay(2);
    }
    gotchi_audio::stopAsyncPttTask();
    gotchi_audio::playChime("ptt_stop");
    gotchi_audio::WavView wav = gotchi_audio::finishPttRecording();

    if (wav.rms < PTT_MIN_RMS || wav.length < PTT_MIN_BYTES) {
        ui.state = UiState::IDLE;
        ui.status_text = "TOO SHORT";
        panel.draw(ui);
        delay(1500);
        showIdle();
        return;
    }

    if (WiFi.status() != WL_CONNECTED) {
        ui.state = UiState::OFFLINE;
        ui.status_text = "NO WIFI";
        panel.draw(ui);
        delay(2000);
        showIdle();
        return;
    }

    ui.state = UiState::TRANSCRIBING;
    ui.status_text = "TRANSCRIBING...";
    panel.draw(ui);

    bool ok = gotchi_voice::interact(wav, cfg.voice_url, cfg.node_id, ui, onVoiceState, cfg.bearer_token);
    if (!ok) {
        // Hold the error / busy / offline sprite briefly so it is visible.
        delay(2000);
    }
    showIdle();
}

void loop() {
    httpServer.handleClient();
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            Serial.println(handleJsonRpc(line));
        }
    }

    if (pttStable(true)) {
        runPttTurn();
        return;
    }
    gotchi_audio::pumpPreroll();
    delay(2);
}
