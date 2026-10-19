#pragma once
// ============================================================================
// GOTCHI V1 — Camera HAL (T2.5 OV2640 / OV3660 Stock + Optional OV5640 AF)
// ============================================================================

#include <Arduino.h>
#include "esp_camera.h"

namespace gotchi_camera {

struct CameraInfo {
    bool initialized;
    uint16_t sensor_pid;
    const char* sensor_name;
    bool has_autofocus;
};

// Initialize DVP camera bus on XIAO ESP32S3 Sense pins and auto-detect sensor
CameraInfo init();

// Trigger single-shot VCM autofocus if OV5640 is attached (register 0x3022 = 0x08)
bool triggerAutofocus();

// Capture a JPEG frame in PSRAM; caller releases with esp_camera_fb_return(fb)
camera_fb_t* captureJpeg();

} // namespace gotchi_camera
