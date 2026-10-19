#pragma once
// ============================================================================
// GOTCHI UI state — C++ mirror of poc/gotchi_poc.py `GotchiUIState`.
// Field defaults match the Python dataclass.
// ============================================================================

#include <Arduino.h>
#include <string.h>

// Scoped: unscoped BUSY/ERROR collide with ESP-IDF ROM declarations (ets_sys.h).
enum class UiState : uint8_t {
    IDLE,
    LISTENING,
    TRANSCRIBING,
    THINKING,
    SYNTHESIZING,
    SPEAKING,
    ERROR,
    BUSY,
    OFFLINE,
};

static constexpr uint8_t UI_STATE_COUNT = 9;

// Lowercase wire names, indexed by UiState (same spelling as Python VALID_STATES).
static const char* const UI_STATE_NAMES[UI_STATE_COUNT] = {
    "idle", "listening", "transcribing", "thinking", "synthesizing",
    "speaking", "error", "busy", "offline",
};

struct GotchiUIState {
    UiState state = UiState::IDLE;
    String transcript;
    String reply;
    String status_text = "READY (HOLD PTT)";
    String error_code;
    String skin = "gotchi"; // "gotchi" | "zero"
    uint16_t thinking_seconds = 0;
    uint32_t audio_bytes_received = 0;
    uint32_t last_sample_rate = 24000;
    int8_t   battery_pct = -1;       // 0..100% when V1 VBAT divider on D4 is active (-1 if unwired)
    uint16_t battery_mv = 0;         // LiPo millivolts (3300..4200 mV)
    bool     wall_power = false;     // true when 5V VBUS wall brick or USB host power is detected
};

// Unknown or null names map to IDLE (matches the Python VALID_STATES fallback).
static inline UiState uiStateFromString(const char* name) {
    if (!name) return UiState::IDLE;
    for (uint8_t i = 0; i < UI_STATE_COUNT; i++) {
        if (strcmp(name, UI_STATE_NAMES[i]) == 0) return static_cast<UiState>(i);
    }
    return UiState::IDLE;
}
