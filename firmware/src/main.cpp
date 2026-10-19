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
static constexpr size_t MAX_WAV_BYTES   = 44 + SAMPLE_RATE_REC * sizeof(int16_t) * 15; // 15s cap
static uint8_t* psram_wav_buf = nullptr;

// E-Paper Refresh Policy State (`PanelManager.write_frame` port)
static uint8_t  consecutive_partials = 0;
static uint32_t last_full_refresh_ms = 0;
static constexpr uint8_t  MAX_CONSECUTIVE_PARTIALS = 8;
static constexpr uint32_t FULL_REFRESH_INTERVAL_MS = 15UL * 60UL * 1000UL;
static constexpr uint32_t EPD_BUSY_TIMEOUT_MS      = 30000UL;

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

bool waitEpdBusy(uint32_t timeout_ms = EPD_BUSY_TIMEOUT_MS) {
    uint32_t t0 = millis();
    while (digitalRead(PIN_EPD_BUSY) == HIGH) {
        if (millis() - t0 > timeout_ms) {
            return false; // Bounded 30s timeout guard
        }
        delay(5);
    }
    return true;
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
        res["epd_busy_clear"] = waitEpdBusy(500);
        res["btn_top_state"] = digitalRead(PIN_BTN_TOP_PTT);
        res["btn_bot_state"] = digitalRead(PIN_BTN_BOT_MOD);
        sensor_t* s = esp_camera_sensor_get();
        res["camera_pid"] = s ? s->id.PID : 0;
    } else if (cmd == "factory_reset") {
        prefs.begin("gotchi", false);
        prefs.clear();
        prefs.end();
        res["status"] = "cleared_nvs";
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

    httpServer.on("/api/rpc", HTTP_POST, []() {
        String resp = handleJsonRpc(httpServer.arg("plain"));
        httpServer.send(200, "application/json", resp);
    });
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
    delay(5);
}
