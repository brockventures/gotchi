#pragma once
// ============================================================================
// GOTCHI Mirrormere voice client (T3.1) — POST /api/voice/interact.
//   - Multipart WAV upload over WiFiClient (HTTP/1.1, Connection: close).
//   - Streaming SSE reply parser; `sentence` / `audio_chunk` PCM plays as it
//     arrives through gotchi_audio::playBase64PcmChunk.
// Wire contract: docs/MIRRORMERE_VOICE_CLIENT.md ("Live gateway").
// ============================================================================

#include <Arduino.h>
#include "audio_hal.h"
#include "ui_state.h"

namespace gotchi_voice {

using StateCb = void (*)(const GotchiUIState&);

// Uploads the WAV, parses the SSE reply, plays audio as it arrives.
// Returns true if the stream reached `done`. Updates `ui` as events arrive and
// calls `cb(ui)` ONLY when ui.state changes or a transcript/reply text arrives
// (and once on a non-200 HTTP status or on an `error` event).
bool interact(const gotchi_audio::WavView& wav, const String& url, const String& node_id,
              GotchiUIState& ui, StateCb cb);

} // namespace gotchi_voice
