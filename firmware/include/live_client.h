#pragma once
// ============================================================================
// GOTCHI Go Live Bidirectional Streaming Client (F19 / F21 / Section 5b)
//   - Bidirectional audio streaming over WiFiClient / WebSocket or HTTP stream:
//     - Uplink: 16 kHz 16-bit mono PCM chunks.
//     - Downlink: 24 kHz 16-bit mono PCM chunks played over MAX98357A I2S.
//   - Mid-session multimodal injection via BTN_BOT:
//     - Short press: single snapshot JPEG.
//     - Long press (>= cam_long_press_ms): 5-photo burst over 3s.
//   - Exit triggers:
//     - BTN_TOP single press immediately ends session.
//     - VAD silence timeout (configurable live_silence_ms, default 15000 ms).
// ============================================================================

#include <Arduino.h>
#include "audio_hal.h"
#include "ui_state.h"
#include "voice_client.h"

namespace gotchi_live {

enum class SessionEndReason : uint8_t {
    USER_EXIT       = 0, // BTN_TOP pressed
    SILENCE_TIMEOUT = 1, // live_silence_ms elapsed without speech
    NETWORK_ERROR   = 2, // Connection dropped or failed
    DISABLED        = 3, // live_mode disabled
};

struct LiveSessionConfig {
    String voice_url = "";
    String node_id = "gotchi-v1-01";
    String bearer_token = "";
    String audio_out_mode = "speaker";
    uint32_t live_silence_ms = 15000;
    uint32_t vad_rms_lsb = 150;
    uint32_t cam_long_press_ms = 700;
    bool enabled = false;
};

// Snapshot capture callback type for mid-session camera injection
using SnapshotCallback = bool (*)(size_t slot_idx);
using BurstCallback = size_t (*)();

// Runs the interactive bidirectional Go Live session loop until exit.
SessionEndReason runSession(
    const LiveSessionConfig& config,
    GotchiUIState& ui,
    gotchi_voice::StateCb cb,
    SnapshotCallback snap_cb = nullptr,
    BurstCallback burst_cb = nullptr
);

} // namespace gotchi_live
