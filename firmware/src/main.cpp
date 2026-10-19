// ============================================================================
// GOTCHI V1 Edge Firmware — Seeed Studio XIAO ESP32S3 Sense (8MB Flash / 8MB PSRAM)
// Implements Epic 2 (T2.1-T2.7) & Epic 3 (T3.1-T3.2):
//   - Dual-transport JSON-RPC (`USB-C Serial 115200` + `POST /api/rpc` w/ Bearer auth)
//   - Hybrid / Tap-to-Talk / Hold-to-Talk input with 120s PSRAM WAV cap & VAD silence stop
//   - Configurable 500ms circular pre-roll (`usb_only` | `always` | `off`)
//   - Mid-reply Barge-In (`BTN_TOP`) and Cancel/Mute (`BTN_BOT`) within 42ms
//   - Camera snapshot staging (`BTN_BOT`) with 3s voice-attach debounce & standalone fallback
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
    // Voice gateway URL (Mirrormere or Zero gateway; set per device via set_config).
    String voice_url = "http://mirrormere.local:9098/api/voice/interact";
    String node_id = "gotchi-v1-01";
    String wake_mode = "ptt";         // "ptt" | "wake_word"
    String input_mode = "hybrid";     // "hybrid" | "tap" | "hold"
    String preroll_mode = "usb_host"; // "usb_host" (or "usb_only") | "always" | "off"
    String audio_out_mode = "speaker";// "speaker" | "discord_voice" | "ble_phone"
    String skin = "zero";             // "zero" | "gotchi"
    String bearer_token = "";         // Per-device Bearer token for off-LAN / tunnel auth (T3.2)
    String wifi_ssid = "";
    String wifi_psk = "";
    uint32_t ptt_max_ms = 120000;     // 120s max recording cap in 8MB PSRAM (3.84 MB)
    uint32_t ptt_min_ms = 250;        // 250ms minimum floor
    uint32_t ptt_min_rms_lsb = 50;    // 50 LSB minimum RMS energy
    uint32_t tap_latch_ms = 500;      // Press released < 500ms latches into hands-free Tap-to-Talk
    uint32_t vad_silence_ms = 1500;   // 1.5s trailing silence ends Tap-to-Talk turn
    uint32_t vad_rms_lsb = 150;       // 150 LSB speech detection threshold for VAD silence timer
    uint32_t snap_window_ms = 3000;   // 3.0s debounce window to attach snapshot to next voice prompt
    String default_image_prompt = "Describe what you see in this snapshot briefly.";
} cfg;

static bool constantTimeEquals(const String& a, const String& b) {
    if (a.length() != b.length()) return false;
    uint8_t diff = 0;
    for (size_t i = 0; i < a.length(); ++i) {
        diff |= (uint8_t)(a[i] ^ b[i]);
    }
    return diff == 0;
}

static constexpr uint32_t SAMPLE_RATE_REC = 16000;
static constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;
static constexpr uint32_t BTN_DEBOUNCE_MS = 30;
static constexpr uint32_t VAD_INITIAL_TIMEOUT_MS = 5000; // Max wait for speech to start in tap mode
static constexpr size_t   MAX_STAGED_JPEG_BYTES = 128 * 1024;

// Staged camera snapshot state (BTN_BOT)
static uint8_t* s_staged_jpeg_buf = nullptr;
static size_t   s_staged_jpeg_len = 0;
static bool     s_staged_jpeg_active = false;
static uint32_t s_staged_jpeg_ts = 0;
static bool     s_barge_in_pending = false;

// E-paper panel + refresh policy live in epd_panel.{h,cpp}.
EpdPanel panel;

// Note on XIAO ESP32S3 schematic: VBUS (5V) feeds the charger IC through a diode
// and is not wired to any GPIO ADC pin. On ESP32-S3, `bool(Serial)` checks the
// native USB Serial/JTAG controller's host connection state (SOF frames present).
static bool isUsbDataHostConnected() {
    return (bool)Serial;
}

static void applyPrerollPolicy() {
    if (cfg.preroll_mode == "always") {
        gotchi_audio::setPrerollEnabled(true);
    } else if (cfg.preroll_mode == "off") {
        gotchi_audio::setPrerollEnabled(false);
    } else {
        // "usb_only": active when enumerated on USB host power/data
        gotchi_audio::setPrerollEnabled(isUsbDataHostConnected());
    }
}

void loadConfig() {
    prefs.begin("gotchi", true);
    cfg.hub_url              = prefs.getString("hub_url", cfg.hub_url);
    cfg.voice_url            = prefs.getString("voice_url", cfg.voice_url);
    cfg.node_id              = prefs.getString("node_id", cfg.node_id);
    cfg.wake_mode            = prefs.getString("wake_mode", cfg.wake_mode);
    cfg.input_mode           = prefs.getString("input_mode", cfg.input_mode);
    cfg.preroll_mode         = prefs.getString("preroll_mode", cfg.preroll_mode);
    cfg.audio_out_mode       = prefs.getString("audio_out_mode", cfg.audio_out_mode);
    cfg.skin                 = prefs.getString("skin", cfg.skin);
    cfg.bearer_token         = prefs.getString("bearer_token", "");
    cfg.wifi_ssid            = prefs.getString("wifi_ssid", "");
    cfg.wifi_psk             = prefs.getString("wifi_psk", "");
    cfg.ptt_max_ms           = prefs.getUInt("ptt_max_ms", cfg.ptt_max_ms);
    cfg.ptt_min_ms           = prefs.getUInt("ptt_min_ms", cfg.ptt_min_ms);
    cfg.ptt_min_rms_lsb      = prefs.getUInt("ptt_min_rms", cfg.ptt_min_rms_lsb);
    cfg.tap_latch_ms         = prefs.getUInt("tap_latch_ms", cfg.tap_latch_ms);
    cfg.vad_silence_ms       = prefs.getUInt("vad_sil_ms", cfg.vad_silence_ms);
    cfg.vad_rms_lsb          = prefs.getUInt("vad_rms_lsb", cfg.vad_rms_lsb);
    cfg.snap_window_ms       = prefs.getUInt("snap_win_ms", cfg.snap_window_ms);
    cfg.default_image_prompt = prefs.getString("img_prompt", cfg.default_image_prompt);
    prefs.end();
    if (cfg.ptt_max_ms > 120000) cfg.ptt_max_ms = 120000;
    if (cfg.ptt_max_ms < 1000)   cfg.ptt_max_ms = 1000;
}

void saveConfig() {
    prefs.begin("gotchi", false);
    prefs.putString("hub_url", cfg.hub_url);
    prefs.putString("voice_url", cfg.voice_url);
    prefs.putString("node_id", cfg.node_id);
    prefs.putString("wake_mode", cfg.wake_mode);
    prefs.putString("input_mode", cfg.input_mode);
    prefs.putString("preroll_mode", cfg.preroll_mode);
    prefs.putString("audio_out_mode", cfg.audio_out_mode);
    prefs.putString("skin", cfg.skin);
    prefs.putString("bearer_token", cfg.bearer_token);
    prefs.putString("wifi_ssid", cfg.wifi_ssid);
    prefs.putString("wifi_psk", cfg.wifi_psk);
    prefs.putUInt("ptt_max_ms", cfg.ptt_max_ms);
    prefs.putUInt("ptt_min_ms", cfg.ptt_min_ms);
    prefs.putUInt("ptt_min_rms", cfg.ptt_min_rms_lsb);
    prefs.putUInt("tap_latch_ms", cfg.tap_latch_ms);
    prefs.putUInt("vad_sil_ms", cfg.vad_silence_ms);
    prefs.putUInt("vad_rms_lsb", cfg.vad_rms_lsb);
    prefs.putUInt("snap_win_ms", cfg.snap_window_ms);
    prefs.putString("img_prompt", cfg.default_image_prompt);
    prefs.end();
    applyPrerollPolicy();
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
        res["input_mode"] = cfg.input_mode;
        res["preroll_mode"] = cfg.preroll_mode;
        res["audio_out_mode"] = cfg.audio_out_mode;
        res["skin"] = cfg.skin;
        res["bearer_token_set"] = (cfg.bearer_token.length() > 0);
        res["wifi_ssid"] = cfg.wifi_ssid;
        res["ptt_max_ms"] = cfg.ptt_max_ms;
        res["ptt_min_ms"] = cfg.ptt_min_ms;
        res["ptt_min_rms_lsb"] = cfg.ptt_min_rms_lsb;
        res["tap_latch_ms"] = cfg.tap_latch_ms;
        res["vad_silence_ms"] = cfg.vad_silence_ms;
        res["vad_rms_lsb"] = cfg.vad_rms_lsb;
        res["snap_window_ms"] = cfg.snap_window_ms;
        res["default_image_prompt"] = cfg.default_image_prompt;
        res["usb_host_connected"] = isUsbDataHostConnected();
        res["psram_free"] = ESP.getFreePsram();
        res["fw_version"] = GOTCHI_FW_VERSION;
    } else if (cmd == "set_config") {
        if (req["hub_url"].is<const char*>()) cfg.hub_url = req["hub_url"].as<String>();
        if (req["voice_url"].is<const char*>()) cfg.voice_url = req["voice_url"].as<String>();
        if (req["node_id"].is<const char*>()) cfg.node_id = req["node_id"].as<String>();
        if (req["wake_mode"].is<const char*>()) cfg.wake_mode = req["wake_mode"].as<String>();
        if (req["input_mode"].is<const char*>()) cfg.input_mode = req["input_mode"].as<String>();
        if (req["preroll_mode"].is<const char*>()) cfg.preroll_mode = req["preroll_mode"].as<String>();
        if (req["audio_out_mode"].is<const char*>()) cfg.audio_out_mode = req["audio_out_mode"].as<String>();
        if (req["skin"].is<const char*>()) cfg.skin = req["skin"].as<String>();
        if (req["bearer_token"].is<const char*>()) cfg.bearer_token = req["bearer_token"].as<String>();
        if (req["ptt_max_ms"].is<uint32_t>()) {
            uint32_t v = req["ptt_max_ms"].as<uint32_t>();
            cfg.ptt_max_ms = v > 120000 ? 120000 : (v < 1000 ? 1000 : v);
        }
        if (req["ptt_min_ms"].is<uint32_t>()) cfg.ptt_min_ms = req["ptt_min_ms"].as<uint32_t>();
        if (req["ptt_min_rms_lsb"].is<uint32_t>()) cfg.ptt_min_rms_lsb = req["ptt_min_rms_lsb"].as<uint32_t>();
        if (req["tap_latch_ms"].is<uint32_t>()) cfg.tap_latch_ms = req["tap_latch_ms"].as<uint32_t>();
        if (req["vad_silence_ms"].is<uint32_t>()) cfg.vad_silence_ms = req["vad_silence_ms"].as<uint32_t>();
        if (req["vad_rms_lsb"].is<uint32_t>()) cfg.vad_rms_lsb = req["vad_rms_lsb"].as<uint32_t>();
        if (req["snap_window_ms"].is<uint32_t>()) cfg.snap_window_ms = req["snap_window_ms"].as<uint32_t>();
        if (req["default_image_prompt"].is<const char*>()) {
            cfg.default_image_prompt = req["default_image_prompt"].as<String>();
        }
        saveConfig();
    } else if (cmd == "set_wifi") {
        cfg.wifi_ssid = req["ssid"] | cfg.wifi_ssid;
        cfg.wifi_psk  = req["psk"]  | cfg.wifi_psk;
        saveConfig();
    } else if (cmd == "self_test") {
        res["psram_ok"] = (psramFound() && ESP.getFreePsram() > 2000000);
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

static bool btnStable(uint8_t pin, bool pressed) {
    const int want = pressed ? LOW : HIGH;
    if (digitalRead(pin) != want) return false;
    delay(BTN_DEBOUNCE_MS);
    return digitalRead(pin) == want;
}

static void waitForButtonRelease(uint8_t pin, uint32_t max_wait_ms = 2000) {
    uint32_t t0 = millis();
    while (digitalRead(pin) == LOW && (millis() - t0 < max_wait_ms)) {
        delay(5);
    }
}

static void showIdle() {
    GotchiUIState idle_ui;
    idle_ui.skin = cfg.skin;
    if (s_staged_jpeg_active) {
        idle_ui.status_text = "SNAP STAGED";
    }
    panel.draw(idle_ui);
}

static void onVoiceState(const GotchiUIState& ui) {
    panel.draw(ui);
}

// Polled every ~42ms during TTS playback and SSE wait.
// BTN_TOP triggers immediate Barge-In (abort playback + start new voice recording).
// BTN_BOT triggers immediate Cancel / Mute (abort playback + return to IDLE).
static gotchi_voice::InteractResult pollVoiceAbort() {
    httpServer.handleClient();
    if (digitalRead(PIN_BTN_TOP_PTT) == LOW && btnStable(PIN_BTN_TOP_PTT, true)) {
        return gotchi_voice::InteractResult::ABORT_BARGE_IN;
    }
    if (digitalRead(PIN_BTN_BOT_MOD) == LOW && btnStable(PIN_BTN_BOT_MOD, true)) {
        return gotchi_voice::InteractResult::ABORT_CANCEL;
    }
    return gotchi_voice::InteractResult::DONE;
}

static void dispatchVoiceOrSnap(const gotchi_audio::WavView& wav, bool include_staged_snap, bool is_standalone_snap) {
    GotchiUIState ui;
    ui.skin = cfg.skin;

    if (WiFi.status() != WL_CONNECTED) {
        ui.state = UiState::OFFLINE;
        ui.status_text = "NO WIFI";
        panel.draw(ui);
        delay(2000);
        showIdle();
        return;
    }

    ui.state = UiState::TRANSCRIBING;
    ui.status_text = is_standalone_snap ? "SENDING SNAP..." : "TRANSCRIBING...";
    panel.draw(ui);

    gotchi_voice::ImageAttachment img;
    const gotchi_voice::ImageAttachment* img_ptr = nullptr;
    if (include_staged_snap && s_staged_jpeg_active && s_staged_jpeg_buf && s_staged_jpeg_len > 0) {
        img.data = s_staged_jpeg_buf;
        img.length = s_staged_jpeg_len;
        if (is_standalone_snap) {
            img.default_prompt = cfg.default_image_prompt;
        }
        img_ptr = &img;
        s_staged_jpeg_active = false;
        s_staged_jpeg_len = 0;
    }

    gotchi_voice::InteractResult result = gotchi_voice::InteractResult::DONE;
    bool ok = gotchi_voice::interact(
        wav, cfg.voice_url, cfg.node_id, ui, onVoiceState, cfg.bearer_token,
        img_ptr, pollVoiceAbort, &result
    );

    if (result == gotchi_voice::InteractResult::ABORT_BARGE_IN) {
        s_barge_in_pending = true;
        return;
    }
    if (result == gotchi_voice::InteractResult::ABORT_CANCEL) {
        waitForButtonRelease(PIN_BTN_BOT_MOD);
        showIdle();
        return;
    }
    if (!ok) {
        delay(2000);
    }
    showIdle();
}

// Stage a camera JPEG snapshot in PSRAM when BTN_BOT is pressed in IDLE.
// Attaches to the next voice turn if BTN_TOP is pressed within `cfg.snap_window_ms` (default 3s),
// or dispatches standalone with `cfg.default_image_prompt` once the window expires.
static void stageCameraSnapshot() {
    GotchiUIState ui;
    ui.skin = cfg.skin;
    waitForButtonRelease(PIN_BTN_BOT_MOD);

    if (!s_staged_jpeg_buf) {
        ui.state = UiState::ERROR;
        ui.status_text = "NO SNAP BUF";
        panel.draw(ui);
        delay(1500);
        showIdle();
        return;
    }

    camera_fb_t* fb = gotchi_camera::captureJpeg();
    if (!fb || !fb->buf || fb->len == 0 || fb->len > MAX_STAGED_JPEG_BYTES) {
        if (fb) esp_camera_fb_return(fb);
        gotchi_audio::playChime("error");
        ui.state = UiState::ERROR;
        ui.status_text = "CAM ERROR";
        panel.draw(ui);
        delay(1500);
        showIdle();
        return;
    }

    memcpy(s_staged_jpeg_buf, fb->buf, fb->len);
    s_staged_jpeg_len = fb->len;
    s_staged_jpeg_active = true;
    s_staged_jpeg_ts = millis();
    esp_camera_fb_return(fb);

    gotchi_audio::playChime("snap");
    showIdle();
}

// One voice turn supporting:
//   - "hold" mode: hold BTN_TOP to record, release to send.
//   - "tap" mode: tap BTN_TOP to open mic, auto-stops after `cfg.vad_silence_ms` (1.5s)
//     of trailing silence once speech is heard (or tap BTN_TOP again to send immediately).
//   - "hybrid" mode (default): releasing BTN_TOP within `cfg.tap_latch_ms` (500ms) latches
//     into hands-free Tap-to-Talk; holding longer than `cfg.tap_latch_ms` stops on release.
// Pressing BTN_BOT during recording cancels the turn without uploading.
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
    ui.status_text = s_staged_jpeg_active ? "LISTENING (+SNAP)..." : "LISTENING...";
    panel.draw(ui);

    const float vad_thresh = (float)cfg.vad_rms_lsb / 32768.0f;
    const float min_rms    = (float)cfg.ptt_min_rms_lsb / 32768.0f;
    const size_t min_bytes = 44 + (SAMPLE_RATE_REC * sizeof(int16_t) * cfg.ptt_min_ms) / 1000;

    uint32_t t0 = millis();
    uint32_t last_speech_ts = t0;
    bool speech_heard = false;
    bool released_once = (digitalRead(PIN_BTN_TOP_PTT) == HIGH);
    bool latched_tap_mode = (cfg.input_mode == "tap");
    bool cancelled = false;

    while (millis() - t0 < cfg.ptt_max_ms) {
        uint32_t elapsed = millis() - t0;
        if (!async_running) gotchi_audio::pollPttRecording();
        httpServer.handleClient();

        // BTN_BOT during recording cancels the turn immediately
        if (digitalRead(PIN_BTN_BOT_MOD) == LOW && btnStable(PIN_BTN_BOT_MOD, true)) {
            cancelled = true;
            break;
        }

        if (!released_once) {
            if (btnStable(PIN_BTN_TOP_PTT, false)) {
                released_once = true;
                if (cfg.input_mode == "hold") {
                    break;
                } else if (cfg.input_mode == "hybrid") {
                    if (elapsed <= cfg.tap_latch_ms) {
                        latched_tap_mode = true; // Quick tap -> latch into hands-free VAD listening
                    } else {
                        break; // Held past tap_latch_ms -> classic PTT release-to-send
                    }
                }
            }
        } else if (latched_tap_mode) {
            // In latched Tap-to-Talk mode, a second tap of BTN_TOP finishes and sends immediately
            if (digitalRead(PIN_BTN_TOP_PTT) == LOW && btnStable(PIN_BTN_TOP_PTT, true)) {
                waitForButtonRelease(PIN_BTN_TOP_PTT);
                break;
            }
        }

        // Track rolling 100ms RMS energy for Tap-to-Talk end-of-speech silence detection
        float recent_rms = gotchi_audio::getRecentRms(1600);
        if (recent_rms >= vad_thresh) {
            speech_heard = true;
            last_speech_ts = millis();
        } else if (latched_tap_mode && released_once) {
            if (speech_heard && (millis() - last_speech_ts >= cfg.vad_silence_ms)) {
                break; // User finished speaking and paused for vad_silence_ms (1.5s)
            }
            if (!speech_heard && (elapsed >= VAD_INITIAL_TIMEOUT_MS)) {
                break; // No speech detected within initial window
            }
        }

        delay(5);
    }

    gotchi_audio::stopAsyncPttTask();

    if (cancelled) {
        waitForButtonRelease(PIN_BTN_BOT_MOD);
        gotchi_audio::playChime("error");
        showIdle();
        return;
    }

    gotchi_audio::playChime("ptt_stop");
    gotchi_audio::WavView wav = gotchi_audio::finishPttRecording();

    if (wav.rms < min_rms || wav.length < min_bytes) {
        ui.state = UiState::IDLE;
        ui.status_text = "TOO SHORT";
        panel.draw(ui);
        delay(1500);
        showIdle();
        return;
    }

    dispatchVoiceOrSnap(wav, s_staged_jpeg_active, false);
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN_BTN_TOP_PTT, INPUT_PULLUP);
    pinMode(PIN_BTN_BOT_MOD, INPUT_PULLUP);
    pinMode(PIN_EPD_BUSY, INPUT);

    if (psramFound()) {
        s_staged_jpeg_buf = (uint8_t*)ps_malloc(MAX_STAGED_JPEG_BYTES);
    }
    loadConfig();

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
    applyPrerollPolicy();
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

void loop() {
    httpServer.handleClient();
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            Serial.println(handleJsonRpc(line));
        }
    }

    // If user barged in with BTN_TOP during TTS playback, jump straight into recording
    if (s_barge_in_pending) {
        s_barge_in_pending = false;
        runPttTurn();
        return;
    }

    // Top button: start Hybrid / Tap-to-Talk / Hold-to-Talk voice turn
    if (btnStable(PIN_BTN_TOP_PTT, true)) {
        runPttTurn();
        return;
    }

    // Bottom button in IDLE: capture & stage camera snapshot
    if (btnStable(PIN_BTN_BOT_MOD, true)) {
        stageCameraSnapshot();
        return;
    }

    // If a staged camera snapshot wasn't paired with a voice prompt within `snap_window_ms` (3s),
    // dispatch it standalone with `default_image_prompt`.
    if (s_staged_jpeg_active && (millis() - s_staged_jpeg_ts >= cfg.snap_window_ms)) {
        gotchi_audio::WavView silent_wav = gotchi_audio::buildSilentWav(250);
        dispatchVoiceOrSnap(silent_wav, true, true);
        return;
    }

    applyPrerollPolicy();
    gotchi_audio::pumpPreroll();
    delay(2);
}
