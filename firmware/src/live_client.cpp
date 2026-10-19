// ============================================================================
// GOTCHI Go Live Bidirectional Streaming Client Implementation (F19 / F21)
// ============================================================================

#include "live_client.h"
#include "pins.h"
#include "log_buffer.h"
#include <WiFi.h>

namespace gotchi_live {
namespace {

static bool isButtonPressed(uint8_t pin) {
    if (digitalRead(pin) != LOW) return false;
    delay(20);
    return digitalRead(pin) == LOW;
}

static void waitForRelease(uint8_t pin, uint32_t max_wait_ms = 2000) {
    uint32_t t0 = millis();
    while (digitalRead(pin) == LOW && (millis() - t0 < max_wait_ms)) {
        delay(5);
    }
}

} // namespace

SessionEndReason runSession(
    const LiveSessionConfig& config,
    GotchiUIState& ui,
    gotchi_voice::StateCb cb,
    SnapshotCallback snap_cb,
    BurstCallback burst_cb
) {
    if (!config.enabled) {
        gotchi_log::RingLogger.info("live", "Go Live session rejected: live_mode is disabled");
        return SessionEndReason::DISABLED;
    }

    if (WiFi.status() != WL_CONNECTED) {
        gotchi_log::RingLogger.warn("live", "Go Live session rejected: no WiFi connection");
        ui.state = UiState::OFFLINE;
        ui.status_text = "NO WIFI";
        if (cb) cb(ui);
        return SessionEndReason::NETWORK_ERROR;
    }

    waitForRelease(PIN_BTN_TOP_PTT);
    gotchi_log::RingLogger.info("live", "Starting Go Live bidirectional session");
    gotchi_audio::playChime("ptt_start");

    ui.state = UiState::LISTENING;
    ui.status_text = "LIVE ACTIVE";
    if (cb) cb(ui);

    const float vad_thresh = (float)config.vad_rms_lsb / 32768.0f;
    uint32_t last_speech_ts = millis();
    uint32_t session_start = millis();
    uint32_t last_audio_pump_ts = millis();

    SessionEndReason exit_reason = SessionEndReason::USER_EXIT;

    while (true) {
        // 1. Exit Check: BTN_TOP single press immediately ends session (F19)
        if (isButtonPressed(PIN_BTN_TOP_PTT)) {
            waitForRelease(PIN_BTN_TOP_PTT);
            gotchi_log::RingLogger.info("live", "User ended Go Live session via BTN_TOP");
            exit_reason = SessionEndReason::USER_EXIT;
            break;
        }

        // 2. Mid-Session Camera Snapshot / Burst via BTN_BOT (F19 / F20)
        if (isButtonPressed(PIN_BTN_BOT_MOD)) {
            uint32_t bot_press_ts = millis();
            bool is_burst = false;
            while (digitalRead(PIN_BTN_BOT_MOD) == LOW) {
                if (millis() - bot_press_ts >= config.cam_long_press_ms) {
                    is_burst = true;
                    break;
                }
                delay(5);
            }

            if (is_burst) {
                // Long press: 5-frame burst capture injected into session
                gotchi_log::RingLogger.info("live", "Injecting 5-photo burst into Live session");
                if (burst_cb) {
                    size_t count = burst_cb();
                    if (count > 0) {
                        gotchi_audio::playChime("snap");
                        ui.status_text = "LIVE (+BURST)";
                        if (cb) cb(ui);
                    }
                }
                waitForRelease(PIN_BTN_BOT_MOD);
            } else {
                // Short press on release: single snapshot injected
                waitForRelease(PIN_BTN_BOT_MOD);
                gotchi_log::RingLogger.info("live", "Injecting single snapshot into Live session");
                if (snap_cb && snap_cb(0)) {
                    gotchi_audio::playChime("snap");
                    ui.status_text = "LIVE (+SNAP)";
                    if (cb) cb(ui);
                }
            }
            last_speech_ts = millis(); // Refresh silence timer on active camera interaction
        }

        // 3. Audio sampling & VAD silence check (16 kHz 16-bit mono)
        gotchi_audio::pumpPreroll();
        float recent_rms = gotchi_audio::getRecentRms(1600);
        if (recent_rms >= vad_thresh) {
            last_speech_ts = millis();
            if (ui.state != UiState::LISTENING) {
                ui.state = UiState::LISTENING;
                ui.status_text = "LIVE (SPEAKING)";
                if (cb) cb(ui);
            }
        } else {
            // Check silence timeout
            if (millis() - last_speech_ts >= config.live_silence_ms) {
                gotchi_log::RingLogger.info("live", "Go Live session ended: silence timeout reached");
                exit_reason = SessionEndReason::SILENCE_TIMEOUT;
                break;
            }
        }

        // 4. Yield / pacing
        delay(10);
    }

    gotchi_audio::playChime("ptt_stop");
    gotchi_audio::muteSpeaker();
    gotchi_log::RingLogger.info("live", "Go Live session finished");

    return exit_reason;
}

} // namespace gotchi_live
