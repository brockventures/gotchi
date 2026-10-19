#include <SPI.h>
#include <string.h>
#include "epd_panel.h"

// Refresh state. The RTC_DATA_ATTR variables survive deep sleep (cold boot
// resets them to these initializers). last_full_ms is RAM only: millis()
// restarts at 0 after every wake, so elapsed time is split across the two.
RTC_DATA_ATTR bool     rtc_first_frame_pending = true;
RTC_DATA_ATTR uint8_t  rtc_consecutive_partials = 0;
RTC_DATA_ATTR uint32_t rtc_ms_since_full = 0;
static uint32_t last_full_ms = 0;

bool epdWaitBusy(uint32_t timeout_ms) {
    uint32_t t0 = millis();
    while (digitalRead(PIN_EPD_BUSY) == HIGH) {
        if (millis() - t0 > timeout_ms) {
            return false;
        }
        delay(5);
    }
    return true;
}

EpdPanel::EpdPanel()
    : display_(GxEPD2_154_D67(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY)) {}

void EpdPanel::begin() {
    SPI.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, PIN_EPD_CS);
    display_.init(115200, rtc_first_frame_pending, 2, false);
    display_.setRotation(0);
}

const char* EpdPanel::selectMode(bool force_full) {
    // Same rules as RefreshTracker.select_refresh_mode.
    if (force_full || rtc_first_frame_pending) return "full";
    if (rtc_consecutive_partials >= MAX_CONSECUTIVE_PARTIALS) return "full";
    uint32_t elapsed = rtc_ms_since_full + (millis() - last_full_ms);
    if (elapsed >= FULL_REFRESH_INTERVAL_MS) return "full";
    return "partial";
}

bool EpdPanel::draw(const GotchiUIState& ui, bool force_full) {
    const char* mode = selectMode(force_full);
    bool full = (strcmp(mode, "full") == 0);
    last_mode_ = mode;

    if (full) {
        display_.setFullWindow();
    } else {
        display_.setPartialWindow(0, 0, 200, 200);
    }

    display_.firstPage();
    do {
        renderFrame(display_, ui, mode);
    } while (display_.nextPage());

    // GxEPD2 does not report refresh failure, so BUSY staying HIGH past the
    // timeout is the only failure signal available here.
    bool ok = epdWaitBusy(EPD_BUSY_TIMEOUT_MS);
    if (!ok) {
        rtc_first_frame_pending = true;  // recover with a full refresh next time
        display_.hibernate();
        return false;
    }

    if (full) {
        rtc_consecutive_partials = 0;
        last_full_ms = millis();
        rtc_ms_since_full = 0;
        rtc_first_frame_pending = false;
    } else {
        rtc_consecutive_partials++;
    }

    display_.hibernate();
    return true;
}

void EpdPanel::prepareDeepSleep() {
    // Move the RAM timestamp forward so a later call does not count the same time twice.
    rtc_ms_since_full += millis() - last_full_ms;
    last_full_ms = millis();
}
