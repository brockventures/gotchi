#pragma once
// ============================================================================
// GOTCHI — Mirrormere voice client (T3.1). Wire spec: docs/MIRRORMERE_VOICE_CLIENT.md.
//   - POST /api/voice/interact (multipart WAV upload, PSRAM body buffer)
//   - SSE stream -> GotchiUIState updates; audio_chunk -> AudioSink (I2S playback)
// ============================================================================

#include <Arduino.h>
#include <functional>
#include <stddef.h>
#include <stdint.h>
#include "audio_hal.h"
#include "sse_parser.h"
#include "ui_state.h"

namespace gotchi_hub {

struct SseEvent {
    String name;
    String data;
};

// Wraps the pure gotchi_sse::Parser and converts events to Arduino String.
class SseParser {
public:
    void feed(const char* chunk, size_t len, std::function<void(const SseEvent&)> onEvent);
    void finish(std::function<void(const SseEvent&)> onEvent);

private:
    gotchi_sse::Parser parser_;
};

// Where audio_chunk PCM goes. Indirection so applyEvent runs without hardware.
struct AudioSink {
    std::function<bool(const char*, size_t, uint32_t)> play;
};

// Sink that plays through gotchi_audio::playBase64PcmChunk (MAX98357A I2S).
AudioSink defaultAudioSink();

// Applies one SSE event to ui (port of flush_event in poc/gotchi_poc.py).
// Malformed JSON is ignored.
void applyEvent(const SseEvent& ev, GotchiUIState& ui, AudioSink& sink);

enum class InteractResult { OK, HTTP_400, HTTP_409, HTTP_500, HTTP_503, NETWORK_ERROR, TIMEOUT };

// Uploads wav to hub_url + "/api/voice/interact" and streams the SSE reply into ui.
// onUi is called after each applied SSE event. Error statuses set ui (ERROR/BUSY/OFFLINE)
// and return without calling onUi; the caller draws ui.
InteractResult interact(const String& hub_url, const String& node_id, const gotchi_audio::WavView& wav,
                        GotchiUIState& ui, std::function<void(const GotchiUIState&)> onUi);

} // namespace gotchi_hub
