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
#include "mirrormere_client.h"

static Preferences prefs;
static WebServer httpServer(80);

struct GotchiConfig {
    String hub_url = "http://mirrormere.local:8080";
    String node_id = "gotchi-v1-01";
    String wake_mode = "ptt";         // "ptt" | "wake_word"
    String audio_out_mode = "speaker";// "speaker" | "discord_voice" | "ble_phone"
    String wifi_ssid = "";
    String wifi_psk = "";
} cfg;

// PSRAM Audio Buffers (16 kHz 16-bit mono recording + 500ms circular pre-roll)
static constexpr size_t SAMPLE_RATE_REC = 16000;
static constexpr size_t PREROLL_BYTES   = SAMPLE_RATE_REC * sizeof(int16_t) / 2; // 16 KB (500ms)

// PTT state machine (T3.1)
static constexpr uint32_t PTT_DEBOUNCE_MS = 30;
static constexpr uint32_t PTT_MAX_MS      = 15000;
// WavView::rms is normalized to [0,1]; this floor is in int16 LSB units (RMS 50 / 32768).
static constexpr float    PTT_MIN_RMS_LSB = 50.0f;

// E-paper panel + refresh policy live in epd_panel.{h,cpp}.
EpdPanel panel;

void loadConfig() {
    prefs.begin("gotchi", true);
    cfg.hub_url        = prefs.getString("hub_url", cfg.hub_url);
    cfg.node_id        = prefs.getString("node_id", cfg.node_id);
    cfg.wake_mode      = prefs.getString("wake_mode", cfg.wake_mode);
    cfg.audio_out_mode = prefs.getString("audio_out_mode", cfg.audio_out_mode);
    cfg.wifi_ssid      = prefs.getString("wifi_ssid", "");
    cfg.wifi_psk       = prefs.getString("wifi_psk", "");
    prefs.end();
}

void saveConfig() {
    prefs.begin("gotchi", false);
    prefs.putString("hub_url", cfg.hub_url);
    prefs.putString("node_id", cfg.node_id);
    prefs.putString("wake_mode", cfg.wake_mode);
    prefs.putString("audio_out_mode", cfg.audio_out_mode);
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
        res["node_id"] = cfg.node_id;
        res["wake_mode"] = cfg.wake_mode;
        res["audio_out_mode"] = cfg.audio_out_mode;
        res["wifi_ssid"] = cfg.wifi_ssid;
        res["psram_free"] = ESP.getFreePsram();
        res["fw_version"] = GOTCHI_FW_VERSION;
    } else if (cmd == "set_config") {
        if (req["hub_url"].is<const char*>()) cfg.hub_url = req["hub_url"].as<String>();
        if (req["node_id"].is<const char*>()) cfg.node_id = req["node_id"].as<String>();
        if (req["wake_mode"].is<const char*>()) cfg.wake_mode = req["wake_mode"].as<String>();
        if (req["audio_out_mode"].is<const char*>()) cfg.audio_out_mode = req["audio_out_mode"].as<String>();
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

    loadConfig();
    panel.begin();

    gotchi_audio::init();
    gotchi_camera::init();

    // Provisioned unit: join Home Wi-Fi (slot 0). Unprovisioned: Soft-AP portal.
    bool wifi_failed = false;
    if (cfg.wifi_ssid.length() > 0) {
        WiFi.mode(WIFI_STA);
        WiFi.begin(cfg.wifi_ssid.c_str(), cfg.wifi_psk.c_str());
        uint32_t t0 = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
            delay(100);
        }
        wifi_failed = (WiFi.status() != WL_CONNECTED);
    } else {
        gotchi_portal::startSoftApPortal(httpServer);
    }

    GotchiUIState boot_ui;
    if (wifi_failed) {
        boot_ui.state = UiState::OFFLINE;
        boot_ui.status_text = "WIFI OFFLINE";
    }
    panel.draw(boot_ui);

    httpServer.on("/api/rpc", HTTP_POST, []() {
        String resp = handleJsonRpc(httpServer.arg("plain"));
        httpServer.send(200, "application/json", resp);
    });
    httpServer.begin();
}

// ---------------------------------------------------------------------------
// PTT flow: hold TOP button -> record -> release -> upload -> SSE -> playback
// ---------------------------------------------------------------------------

static bool     s_btn_raw_pressed    = false;
static bool     s_btn_stable_pressed = false;
static uint32_t s_btn_change_ms      = 0;
static bool     s_recording          = false;
static bool     s_wait_release       = false;  // set after the 15 s cap; ignore presses until released
static uint32_t s_rec_start_ms       = 0;

// Button is active-low. Returns the debounced pressed state.
static bool pttPressedDebounced() {
    bool raw = (digitalRead(PIN_BTN_TOP_PTT) == LOW);
    if (raw != s_btn_raw_pressed) {
        s_btn_raw_pressed = raw;
        s_btn_change_ms = millis();
    }
    if (raw != s_btn_stable_pressed && millis() - s_btn_change_ms >= PTT_DEBOUNCE_MS) {
        s_btn_stable_pressed = raw;
    }
    return s_btn_stable_pressed;
}

static void finishAndUpload() {
    gotchi_audio::WavView wav = gotchi_audio::finishPttRecording();
    gotchi_audio::playChime("ptt_stop");

    if (wav.length <= 44 || wav.rms * 32768.0f < PTT_MIN_RMS_LSB) {
        GotchiUIState idle_ui;
        panel.draw(idle_ui);
        return;
    }

    GotchiUIState ui;
    ui.state = UiState::TRANSCRIBING;
    ui.status_text = "TRANSCRIBING";
    panel.draw(ui);

    // Redraw only when the visible state or status line changes (audio_chunk floods are skipped).
    GotchiUIState drawn = ui;
    gotchi_hub::InteractResult r = gotchi_hub::interact(
        cfg.hub_url, cfg.node_id, wav, ui,
        [&drawn](const GotchiUIState& s) {
            if (s.state != drawn.state || s.status_text != drawn.status_text) {
                panel.draw(s);
                drawn = s;
            }
        });

    gotchi_audio::muteSpeaker();
    if (r == gotchi_hub::InteractResult::OK) {
        delay(1500);
    } else {
        panel.draw(ui);  // error / busy / offline sprite set by interact()
        delay(3000);
    }
    GotchiUIState idle_ui;
    panel.draw(idle_ui);
}

static void servicePtt() {
    bool pressed = pttPressedDebounced();

    if (s_wait_release) {
        if (!pressed) s_wait_release = false;
        gotchi_audio::pumpPreroll();
        return;
    }

    if (!s_recording) {
        if (pressed && gotchi_audio::beginPttRecording()) {
            s_recording = true;
            s_rec_start_ms = millis();
            gotchi_audio::playChime("ptt_start");
            GotchiUIState listening;
            listening.state = UiState::LISTENING;
            listening.status_text = "LISTENING";
            panel.draw(listening);
        } else {
            gotchi_audio::pumpPreroll();  // idle: keep the 500 ms pre-roll ring fresh
        }
        return;
    }

    gotchi_audio::pollPttRecording();
    bool capped = (millis() - s_rec_start_ms >= PTT_MAX_MS);
    if (pressed && !capped) return;

    s_recording = false;
    s_wait_release = capped && pressed;
    finishAndUpload();
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
    servicePtt();
    delay(5);
}
