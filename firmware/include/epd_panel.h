#pragma once
// ============================================================================
// GOTCHI e-paper panel driver — Waveshare 1.54" V2 (SSD1681, 200x200) via GxEPD2.
// Port of poc/gotchi_poc.py `RefreshTracker` (policy) and
// `render_sprite_200x200` (layout, see sprite_render.cpp).
// Pins: include/pins.h (do not change here).
// ============================================================================

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <GxEPD2_BW.h>
#include "pins.h"
#include "ui_state.h"

// Refresh policy (RefreshTracker defaults).
static constexpr uint8_t  MAX_CONSECUTIVE_PARTIALS = 8;
static constexpr uint32_t FULL_REFRESH_INTERVAL_MS = 15UL * 60UL * 1000UL;
static constexpr uint32_t EPD_BUSY_TIMEOUT_MS      = 30000UL;

// Bounded wait while BUSY is HIGH. Returns false if still busy at the timeout.
bool epdWaitBusy(uint32_t timeout_ms = EPD_BUSY_TIMEOUT_MS);

// Draws the companion sprite frame (200x200) onto any Adafruit_GFX canvas.
// refresh_mode ("full" | "partial") only selects the header badge.
void renderFrame(Adafruit_GFX& d, const GotchiUIState& ui, const char* refresh_mode);

class EpdPanel {
public:
    EpdPanel();

    // SPI + GxEPD2 init. Call once from setup().
    void begin();

    // "full" | "partial" per the refresh policy.
    const char* selectMode(bool force_full);

    // Renders ui and refreshes the panel. Returns false on BUSY timeout;
    // the next draw is then forced full.
    bool draw(const GotchiUIState& ui, bool force_full = false);

    // Mode chosen by the most recent draw().
    const char* lastMode() const { return last_mode_; }

    // Accumulates elapsed time since the last full refresh into RTC memory.
    // Call before entering deep sleep.
    void prepareDeepSleep();

private:
    GxEPD2_BW<GxEPD2_154_D67, GxEPD2_154_D67::HEIGHT> display_;
    const char* last_mode_ = "full";
};
