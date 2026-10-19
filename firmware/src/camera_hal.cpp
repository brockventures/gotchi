#include "camera_hal.h"
#include "pins.h"

namespace gotchi_camera {

static CameraInfo s_info = {false, 0, "none", false};

CameraInfo init() {
    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = PIN_CAM_Y2;
    config.pin_d1       = PIN_CAM_Y3;
    config.pin_d2       = PIN_CAM_Y4;
    config.pin_d3       = PIN_CAM_Y5;
    config.pin_d4       = PIN_CAM_Y6;
    config.pin_d5       = PIN_CAM_Y7;
    config.pin_d6       = PIN_CAM_Y8;
    config.pin_d7       = PIN_CAM_Y9;
    config.pin_xclk     = PIN_CAM_XCLK;
    config.pin_pclk     = PIN_CAM_PCLK;
    config.pin_vsync    = PIN_CAM_VSYNC;
    config.pin_href     = PIN_CAM_HREF;
    config.pin_sccb_sda = PIN_CAM_SIOD;
    config.pin_sccb_scl = PIN_CAM_SIOC;
    config.pin_pwdn     = -1;
    config.pin_reset    = -1;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size   = FRAMESIZE_VGA; // 640x480 fast multimodal snapshot
    config.jpeg_quality = 12;
    config.fb_count     = psramFound() ? 2 : 1;
    config.fb_location  = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
    config.grab_mode    = CAMERA_GRAB_LATEST;

    if (esp_camera_init(&config) != ESP_OK) {
        return s_info;
    }

    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s_info.initialized = true;
        s_info.sensor_pid  = s->id.PID;
        if (s->id.PID == OV5640_PID) {
            s_info.sensor_name   = "OV5640";
            s_info.has_autofocus = true;
        } else if (s->id.PID == OV3660_PID) {
            s_info.sensor_name   = "OV3660";
            s_info.has_autofocus = false;
        } else {
            s_info.sensor_name   = "OV2640";
            s_info.has_autofocus = false;
        }
    }
    return s_info;
}

bool triggerAutofocus() {
    if (!s_info.initialized || !s_info.has_autofocus) return false;
    sensor_t* s = esp_camera_sensor_get();
    if (!s) return false;
    // OV5640 VCM single-shot autofocus trigger register (0x3022 = 0x08)
    return (s->set_reg(s, 0x3022, 0xFF, 0x08) == 0);
}

camera_fb_t* captureJpeg() {
    if (!s_info.initialized) return nullptr;
    if (s_info.has_autofocus) {
        triggerAutofocus();
        delay(120);
    }
    return esp_camera_fb_get();
}

} // namespace gotchi_camera
