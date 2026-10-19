#pragma once
// ============================================================================
// GOTCHI V1 — Audio HAL (T2.3 PDM Mic Capture & T2.4 MAX98357A I2S TX Player)
//   - T2.3: I2S0 PDM RX on CLK=GPIO42, DATA=GPIO41 (16 kHz, 16-bit mono)
//           with 500ms circular pre-roll ring buffer in 8MB PSRAM & WAV builder
//   - T2.4: I2S1 Standard TX on BCLK=GPIO44 (silent at boot), LRCLK=GPIO43,
//           DIN=GPIO8 for streamed 24 kHz TTS audio chunks & Tamagotchi chimes
// ============================================================================

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

namespace gotchi_audio {

struct WavView {
    const uint8_t* data;
    size_t length;
    float rms;
};

// Initialize PDM Microphone (I2S_NUM_0) and MAX98357A Speaker Amplifier (I2S_NUM_1)
bool init();

// Pump 16 kHz PDM samples into the 500ms circular pre-roll buffer while idle
void pumpPreroll();

// Start PTT recording: copies the 500ms pre-roll into the PSRAM WAV payload buffer
bool beginPttRecording();

// Read available 16 kHz PDM samples during held PTT button (up to 15s max)
size_t pollPttRecording();

// Finalize PTT recording: writes the 44-byte RIFF WAV header and returns buffer view
WavView finishPttRecording();

// Play raw 16-bit signed mono PCM chunk over MAX98357A I2S TX (honors dynamic sample_rate, default 24000 Hz)
bool playPcmChunk(const int16_t* samples, size_t sample_count, uint32_t sample_rate = 24000);

// Play base64-encoded PCM chunk directly from Mirrormere `audio_chunk` SSE event
bool playBase64PcmChunk(const char* b64_data, size_t b64_len, uint32_t sample_rate = 24000);

// Play short synthesized Tamagotchi UI chime ("ptt_start", "ptt_stop", "ready", "error")
void playChime(const char* kind);

// Stop I2S TX clocks so MAX98357A automatically enters <1 uA hardware shutdown
void muteSpeaker();

} // namespace gotchi_audio
