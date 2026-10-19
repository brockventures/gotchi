// ============================================================================
// Companion sprite renderer — C++ port of poc/gotchi_poc.py
// `render_sprite_200x200`. Coordinates are the PIL ones (inclusive bboxes),
// converted to Adafruit_GFX calls. Arcs and thick strokes are built from
// primitives because Adafruit_GFX has no arc or stroke-width API.
// ============================================================================

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include "epd_panel.h"

namespace {

constexpr int CAPTION_COLS = 31;     // 31 * 6 px body glyphs = 186 px, inside 200 px
constexpr int HEADER_TEXT_MAX_PX = 150;

// Uppercase display names (PIL draws state.upper()).
const char* const UI_STATE_UPPER[UI_STATE_COUNT] = {
    "IDLE", "LISTENING", "TRANSCRIBING", "THINKING", "SYNTHESIZING",
    "SPEAKING", "ERROR", "BUSY", "OFFLINE",
};

// PIL bbox [x0,y0,x1,y1] is inclusive. Circular ellipses only in this sprite.
void boxCenter(int x0, int y0, int x1, int y1, int& cx, int& cy, int& r) {
    cx = (x0 + x1) / 2;
    cy = (y0 + y1) / 2;
    r = (x1 - x0) / 2;
}

void fillBoxCircle(Adafruit_GFX& d, int x0, int y0, int x1, int y1, uint16_t c) {
    int cx, cy, r;
    boxCenter(x0, y0, x1, y1, cx, cy, r);
    d.fillCircle(cx, cy, r, c);
}

// PIL ellipse(outline, width=w): concentric rings drawn inward.
void ringBoxCircle(Adafruit_GFX& d, int x0, int y0, int x1, int y1, int w, uint16_t c) {
    int cx, cy, r;
    boxCenter(x0, y0, x1, y1, cx, cy, r);
    for (int i = 0; i < w && r - i >= 0; i++) {
        d.drawCircle(cx, cy, r - i, c);
    }
}

// PIL rectangle(outline, width=w): drawn inward.
void rectOutline(Adafruit_GFX& d, int x0, int y0, int x1, int y1, int w, uint16_t c) {
    for (int i = 0; i < w; i++) {
        d.drawRect(x0 + i, y0 + i, x1 - x0 + 1 - 2 * i, y1 - y0 + 1 - 2 * i, c);
    }
}

// PIL rounded_rectangle(outline, width=w).
void roundRectOutline(Adafruit_GFX& d, int x0, int y0, int x1, int y1, int r, int w, uint16_t c) {
    for (int i = 0; i < w; i++) {
        int rr = r - i;
        if (rr < 0) rr = 0;
        d.drawRoundRect(x0 + i, y0 + i, x1 - x0 + 1 - 2 * i, y1 - y0 + 1 - 2 * i, rr, c);
    }
}

// PIL line(points, width=w).
void thickLine(Adafruit_GFX& d, int x0, int y0, int x1, int y1, int w, uint16_t c) {
    for (int i = -(w - 1) / 2; i <= w / 2; i++) {
        d.drawLine(x0 + i, y0, x1 + i, y1, c);
        d.drawLine(x0, y0 + i, x1, y1 + i, c);
    }
}

// PIL arc(bbox, start, end, width=w). Angles in degrees, clockwise from +x
// (screen y grows downward, same as PIL). Sampled at 1 degree steps.
void arcStroke(Adafruit_GFX& d, int x0, int y0, int x1, int y1,
               float start_deg, float end_deg, int w, uint16_t c) {
    const float cx = (x0 + x1) / 2.0f;
    const float cy = (y0 + y1) / 2.0f;
    const float rx = (x1 - x0) / 2.0f;
    const float ry = (y1 - y0) / 2.0f;
    for (float a = start_deg; a <= end_deg; a += 1.0f) {
        float rad = a * (3.14159265f / 180.0f);
        int px = (int)lroundf(cx + rx * cosf(rad));
        int py = (int)lroundf(cy + ry * sinf(rad));
        d.fillRect(px - w / 2, py - w / 2, w, w, c);
    }
}

// PIL chord(bbox, start=0, end=180, fill=c): the lower half of the ellipse,
// filled. This sprite uses no other chord angles.
void fillLowerHalfEllipse(Adafruit_GFX& d, int x0, int y0, int x1, int y1, uint16_t c) {
    const float cx = (x0 + x1) / 2.0f;
    const float cy = (y0 + y1) / 2.0f;
    const float rx = (x1 - x0) / 2.0f;
    const float ry = (y1 - y0) / 2.0f;
    for (int py = (int)lroundf(cy); py <= y1; py++) {
        float dy = py - cy;
        float t = 1.0f - (dy / ry) * (dy / ry);
        if (t < 0.0f) t = 0.0f;
        int span = (int)lroundf(rx * sqrtf(t));
        d.drawFastHLine((int)lroundf(cx) - span, py, 2 * span + 1, c);
    }
}

// Draws text clipped to max_chars. The body font is the built-in 6x8 font.
// Adafruit's single-color setTextColor(c) also fills the background with c,
// so every text call passes an explicit background.
void printClipped(Adafruit_GFX& d, int x, int y, const char* s, size_t max_chars,
                  uint16_t fg, uint16_t bg) {
    char buf[CAPTION_COLS + 1];
    size_t n = strlen(s);
    if (n > max_chars) n = max_chars;
    if (n > CAPTION_COLS) n = CAPTION_COLS;
    memcpy(buf, s, n);
    buf[n] = '\0';
    d.setTextColor(fg, bg);
    d.setCursor(x, y);
    d.print(buf);
}

// Word-wraps text into at most max_rows rows of cols chars each.
// Breaks at the last space in a row when one exists, otherwise hard-breaks.
// Text beyond the last row is dropped.
void drawWrapped(Adafruit_GFX& d, int x, int y, int pitch, const char* text,
                 int cols, int max_rows, uint16_t fg, uint16_t bg) {
    size_t n = strlen(text);
    size_t pos = 0;
    for (int row = 0; row < max_rows && pos < n; row++) {
        while (pos < n && text[pos] == ' ') pos++;
        if (pos >= n) break;
        size_t stop = n;
        size_t lim = pos + (size_t)cols;
        if (lim < n) {
            stop = lim;
            size_t b = lim;
            while (b > pos && text[b] != ' ') b--;
            if (b > pos) stop = b;
        }
        printClipped(d, x, y + row * pitch, text + pos, stop - pos, fg, bg);
        pos = stop;
    }
}

// Shrinks text until its bounds fit within max_px, then prints it.
void printFitted(Adafruit_GFX& d, int x, int baseline, char* text, int max_px,
                 uint16_t fg, uint16_t bg) {
    int16_t bx, by;
    uint16_t bw, bh;
    d.getTextBounds(text, 0, 0, &bx, &by, &bw, &bh);
    size_t len = strlen(text);
    while (bw > max_px && len > 0) {
        text[--len] = '\0';
        d.getTextBounds(text, 0, 0, &bx, &by, &bw, &bh);
    }
    d.setTextColor(fg, bg);
    d.setCursor(x, baseline);
    d.print(text);
}

}  // namespace

void renderFrame(Adafruit_GFX& d, const GotchiUIState& ui, const char* refresh_mode) {
    d.fillScreen(GxEPD_WHITE);
    d.setTextWrap(false);  // wrapping is done explicitly below; no auto-wrap

    // Header bar (y = 0..20): "GOTCHI // STATE" left, refresh badge right.
    d.fillRect(0, 0, 200, 21, GxEPD_BLACK);
    d.setFont(&FreeSansBold9pt7b);
    char header[40];
    snprintf(header, sizeof(header), "GOTCHI // %s", UI_STATE_UPPER[static_cast<uint8_t>(ui.state)]);
    printFitted(d, 5, 15, header, HEADER_TEXT_MAX_PX, GxEPD_WHITE, GxEPD_BLACK);

    d.setFont(nullptr);
    d.setTextSize(1);
    d.setTextColor(GxEPD_WHITE, GxEPD_BLACK);
    d.setCursor(164, 7);
    d.print(strcmp(refresh_mode, "full") == 0 ? "FULL" : "PART");

    // Outer border, width 2.
    rectOutline(d, 0, 0, 199, 199, 2, GxEPD_BLACK);

    // Character body: rounded box with two ears.
    d.fillRoundRect(42, 30, 117, 105, 18, GxEPD_WHITE);
    roundRectOutline(d, 42, 30, 158, 134, 18, 3, GxEPD_BLACK);
    d.fillTriangle(56, 30, 66, 18, 76, 30, GxEPD_BLACK);
    d.fillTriangle(124, 30, 134, 18, 144, 30, GxEPD_BLACK);

    // Face per state.
    switch (ui.state) {
        case UiState::IDLE:
            // Calm eyes with highlights, subtle smile.
            fillBoxCircle(d, 66, 62, 82, 78, GxEPD_BLACK);
            fillBoxCircle(d, 118, 62, 134, 78, GxEPD_BLACK);
            fillBoxCircle(d, 70, 65, 75, 70, GxEPD_WHITE);
            fillBoxCircle(d, 122, 65, 127, 70, GxEPD_WHITE);
            arcStroke(d, 82, 88, 118, 110, 15, 165, 3, GxEPD_BLACK);
            break;

        case UiState::LISTENING:
            // Wide attentive eyes, open "O" mouth, sound-wave arcs.
            ringBoxCircle(d, 62, 58, 84, 80, 3, GxEPD_BLACK);
            fillBoxCircle(d, 69, 65, 77, 73, GxEPD_BLACK);
            ringBoxCircle(d, 116, 58, 138, 80, 3, GxEPD_BLACK);
            fillBoxCircle(d, 123, 65, 131, 73, GxEPD_BLACK);
            ringBoxCircle(d, 91, 94, 109, 112, 3, GxEPD_BLACK);
            arcStroke(d, 22, 56, 38, 108, 120, 240, 2, GxEPD_BLACK);
            arcStroke(d, 162, 56, 178, 108, -60, 60, 2, GxEPD_BLACK);
            break;

        case UiState::TRANSCRIBING: {
            // Eyes looking right, waveform bars.
            d.fillRect(64, 66, 21, 11, GxEPD_BLACK);
            d.fillRect(116, 66, 21, 11, GxEPD_BLACK);
            static const int bars[] = {6, 14, 10, 18, 8, 14, 6};
            for (int idx = 0; idx < 7; idx++) {
                int h = bars[idx];
                int bx = 72 + idx * 9;
                int top = 104 - h / 2;
                int bottom = 104 + h / 2;
                d.fillRect(bx, top, 6, bottom - top + 1, GxEPD_BLACK);
            }
            break;
        }

        case UiState::THINKING:
        case UiState::SYNTHESIZING:
            // Eyes looking up, mouth line, thought bubbles.
            fillBoxCircle(d, 66, 56, 82, 72, GxEPD_BLACK);
            fillBoxCircle(d, 118, 56, 134, 72, GxEPD_BLACK);
            thickLine(d, 84, 102, 116, 102, 3, GxEPD_BLACK);
            ringBoxCircle(d, 162, 48, 170, 56, 2, GxEPD_BLACK);
            ringBoxCircle(d, 172, 34, 186, 48, 2, GxEPD_BLACK);
            break;

        case UiState::SPEAKING:
            // Chevron eyes `^ ^`, open talking mouth.
            thickLine(d, 64, 74, 74, 62, 3, GxEPD_BLACK);
            thickLine(d, 74, 62, 84, 74, 3, GxEPD_BLACK);
            thickLine(d, 116, 74, 126, 62, 3, GxEPD_BLACK);
            thickLine(d, 126, 62, 136, 74, 3, GxEPD_BLACK);
            fillLowerHalfEllipse(d, 80, 90, 120, 118, GxEPD_BLACK);
            break;

        default:
            // ERROR / BUSY / OFFLINE: X eyes, flat/wavy mouth.
            thickLine(d, 64, 60, 82, 78, 3, GxEPD_BLACK);
            thickLine(d, 82, 60, 64, 78, 3, GxEPD_BLACK);
            thickLine(d, 118, 60, 136, 78, 3, GxEPD_BLACK);
            thickLine(d, 136, 60, 118, 78, 3, GxEPD_BLACK);
            arcStroke(d, 82, 98, 118, 118, 195, 345, 3, GxEPD_BLACK);
            break;
    }

    // Caption tray (y = 140..199): primary text, status line, SR/B info.
    d.fillRect(0, 140, 200, 2, GxEPD_BLACK);
    const char* primary = ui.reply.length() ? ui.reply.c_str()
                        : ui.transcript.length() ? ui.transcript.c_str()
                        : ui.status_text.length() ? ui.status_text.c_str()
                        : "READY";
    drawWrapped(d, 6, 146, 10, primary, CAPTION_COLS, 2, GxEPD_BLACK, GxEPD_WHITE);

    // Python shows the SR/bytes diagnostic only when there is no reply or transcript.
    if (!ui.reply.length() && !ui.transcript.length()) {
        char info[32];
        snprintf(info, sizeof(info), "SR:%uk B:%lu",
                 (unsigned)(ui.last_sample_rate / 1000),
                 (unsigned long)ui.audio_bytes_received);
        printClipped(d, 6, 168, info, CAPTION_COLS, GxEPD_BLACK, GxEPD_WHITE);
    }
    printClipped(d, 6, 182, ui.status_text.c_str(), CAPTION_COLS, GxEPD_BLACK, GxEPD_WHITE);
}
