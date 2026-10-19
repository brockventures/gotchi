#include "audio_hal.h"
#include "pins.h"
#include <driver/i2s.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mbedtls/base64.h>
#include <math.h>
#include <string.h>

namespace gotchi_audio {

static constexpr i2s_port_t PORT_PDM_RX = I2S_NUM_0;
static constexpr i2s_port_t PORT_I2S_TX = I2S_NUM_1;

static constexpr uint32_t REC_SAMPLE_RATE = 16000;
static constexpr size_t   PREROLL_SAMPLES = REC_SAMPLE_RATE / 2; // 500 ms = 8,000 samples (16 KB)
static constexpr size_t   MAX_REC_SAMPLES = REC_SAMPLE_RATE * 120; // 120s max in 8MB PSRAM = 1,920,000 samples (3.84 MB)
static constexpr size_t   WAV_HEADER_SIZE = 44;

static int16_t* s_preroll_ring    = nullptr;
static size_t   s_preroll_head    = 0;
static bool     s_preroll_full    = false;
static bool     s_preroll_enabled = true;

static uint8_t*      s_wav_buf      = nullptr;
static volatile size_t s_rec_samples = 0;
static size_t        s_max_samples  = MAX_REC_SAMPLES;
static uint32_t      s_cur_tx_rate  = 24000;
static AbortCheckFn  s_abort_check  = nullptr;

static void writeWavHeader(uint8_t* dst, uint32_t pcm_bytes, uint32_t sample_rate) {
    uint32_t riff_size   = 36 + pcm_bytes;
    uint32_t byte_rate   = sample_rate * 2;
    uint16_t block_align = 2;
    uint16_t bits        = 16;
    uint16_t fmt_pcm     = 1;
    uint16_t channels    = 1;
    uint32_t fmt_len     = 16;

    memcpy(dst + 0,  "RIFF", 4);
    memcpy(dst + 4,  &riff_size, 4);
    memcpy(dst + 8,  "WAVEfmt ", 8);
    memcpy(dst + 16, &fmt_len, 4);
    memcpy(dst + 20, &fmt_pcm, 2);
    memcpy(dst + 22, &channels, 2);
    memcpy(dst + 24, &sample_rate, 4);
    memcpy(dst + 28, &byte_rate, 4);
    memcpy(dst + 32, &block_align, 2);
    memcpy(dst + 34, &bits, 2);
    memcpy(dst + 36, "data", 4);
    memcpy(dst + 40, &pcm_bytes, 4);
}

bool init() {
    if (!s_preroll_ring) {
        s_preroll_ring = (int16_t*)(psramFound()
            ? ps_malloc(PREROLL_SAMPLES * sizeof(int16_t))
            : malloc(PREROLL_SAMPLES * sizeof(int16_t)));
    }
    if (!s_wav_buf) {
        if (psramFound()) {
            s_max_samples = MAX_REC_SAMPLES;
            s_wav_buf = (uint8_t*)ps_malloc(WAV_HEADER_SIZE + s_max_samples * sizeof(int16_t));
        } else {
            s_max_samples = 32000;
            s_wav_buf = (uint8_t*)malloc(WAV_HEADER_SIZE + s_max_samples * sizeof(int16_t));
        }
    }

    // 1. Configure I2S0 for Onboard PDM Microphone RX (CLK=GPIO42, DATA=GPIO41)
    i2s_config_t rx_cfg = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = REC_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 6,
        .dma_buf_len = 256,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
    };
    i2s_pin_config_t rx_pins = {
        .mck_io_num = I2S_PIN_NO_CHANGE,
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = PIN_PDM_CLK,     // GPIO 42 (PDM CLK)
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = PIN_PDM_DATA,  // GPIO 41 (PDM DATA)
    };
    if (i2s_driver_install(PORT_PDM_RX, &rx_cfg, 0, nullptr) != ESP_OK) return false;
    if (i2s_set_pin(PORT_PDM_RX, &rx_pins) != ESP_OK) return false;

    // 2. Configure I2S1 for MAX98357A Speaker TX (BCLK=GPIO44 silent at boot, LRCLK=GPIO43, DIN=GPIO8)
    i2s_config_t tx_cfg = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = s_cur_tx_rate,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 6,
        .dma_buf_len = 256,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0,
    };
    i2s_pin_config_t tx_pins = {
        .mck_io_num = I2S_PIN_NO_CHANGE,
        .bck_io_num = PIN_I2S_BCLK,   // GPIO 44 (D7)
        .ws_io_num = PIN_I2S_LRCLK,   // GPIO 43 (D6)
        .data_out_num = PIN_I2S_DIN,  // GPIO 8  (D9)
        .data_in_num = I2S_PIN_NO_CHANGE,
    };
    if (i2s_driver_install(PORT_I2S_TX, &tx_cfg, 0, nullptr) != ESP_OK) return false;
    if (i2s_set_pin(PORT_I2S_TX, &tx_pins) != ESP_OK) return false;
    i2s_stop(PORT_I2S_TX); // Keep BCLK idle (<1 uA MAX98357A shutdown) until playback

    return (s_preroll_ring != nullptr && s_wav_buf != nullptr);
}

void setPrerollEnabled(bool enabled) {
    if (s_preroll_enabled == enabled) return;
    s_preroll_enabled = enabled;
    if (!enabled) {
        s_preroll_head = 0;
        s_preroll_full = false;
    }
}

void pumpPreroll() {
    if (!s_preroll_ring || !s_preroll_enabled) return;
    int16_t chunk[128];
    size_t bytes_read = 0;
    if (i2s_read(PORT_PDM_RX, chunk, sizeof(chunk), &bytes_read, 0) == ESP_OK && bytes_read > 0) {
        size_t n = bytes_read / sizeof(int16_t);
        for (size_t i = 0; i < n; ++i) {
            s_preroll_ring[s_preroll_head] = chunk[i];
            s_preroll_head = (s_preroll_head + 1) % PREROLL_SAMPLES;
            if (s_preroll_head == 0) s_preroll_full = true;
        }
    }
}

size_t readLivePcmChunk(int16_t* dst, size_t max_samples, float* out_rms) {
    if (out_rms) *out_rms = 0.0f;
    if (!dst || max_samples == 0) return 0;
    size_t bytes_read = 0;
    if (i2s_read(PORT_PDM_RX, dst, max_samples * sizeof(int16_t), &bytes_read, 0) != ESP_OK || bytes_read < sizeof(int16_t)) {
        return 0;
    }
    size_t n = bytes_read / sizeof(int16_t);
    if (out_rms && n > 0) {
        double sum_sq = 0.0;
        for (size_t i = 0; i < n; ++i) {
            double v = static_cast<double>(dst[i]) / 32768.0;
            sum_sq += v * v;
        }
        *out_rms = static_cast<float>(sqrt(sum_sq / static_cast<double>(n)));
    }
    return n;
}

bool beginPttRecording() {
    if (!s_wav_buf || !s_preroll_ring) return false;
    int16_t* dst = reinterpret_cast<int16_t*>(s_wav_buf + WAV_HEADER_SIZE);
    s_rec_samples = 0;

    if (s_preroll_enabled) {
        // Copy 500ms circular pre-roll into start of WAV buffer so first syllable is never clipped
        if (s_preroll_full) {
            size_t tail_len = PREROLL_SAMPLES - s_preroll_head;
            memcpy(dst, s_preroll_ring + s_preroll_head, tail_len * sizeof(int16_t));
            memcpy(dst + tail_len, s_preroll_ring, s_preroll_head * sizeof(int16_t));
            s_rec_samples = PREROLL_SAMPLES;
        } else if (s_preroll_head > 0) {
            memcpy(dst, s_preroll_ring, s_preroll_head * sizeof(int16_t));
            s_rec_samples = s_preroll_head;
        }
    } else {
        // Flush stale DMA RX samples before starting fresh capture
        int16_t dummy[128];
        size_t bytes_read = 0;
        while (i2s_read(PORT_PDM_RX, dummy, sizeof(dummy), &bytes_read, 0) == ESP_OK && bytes_read > 0) {}
    }
    return true;
}

size_t pollPttRecording() {
    if (!s_wav_buf || s_rec_samples >= s_max_samples) return s_rec_samples;
    int16_t* dst = reinterpret_cast<int16_t*>(s_wav_buf + WAV_HEADER_SIZE);
    size_t room_bytes = (s_max_samples - s_rec_samples) * sizeof(int16_t);
    size_t to_read = room_bytes < 1024 ? room_bytes : 1024;
    size_t bytes_read = 0;
    if (i2s_read(PORT_PDM_RX, dst + s_rec_samples, to_read, &bytes_read, pdMS_TO_TICKS(10)) == ESP_OK) {
        s_rec_samples += bytes_read / sizeof(int16_t);
    }
    return s_rec_samples;
}

static volatile bool s_ptt_task_running = false;
static TaskHandle_t  s_ptt_task_handle  = nullptr;

static void pttRecordTaskFn(void* /*arg*/) {
    while (s_ptt_task_running) {
        pollPttRecording();
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    s_ptt_task_handle = nullptr;
    vTaskDelete(nullptr);
}

bool startAsyncPttTask() {
    if (s_ptt_task_running) return true;
    s_ptt_task_running = true;
    BaseType_t rc = xTaskCreatePinnedToCore(
        pttRecordTaskFn,
        "gotchi_ptt_rx",
        4096,
        nullptr,
        configMAX_PRIORITIES - 2,
        &s_ptt_task_handle,
        0  // Pin to Core 0 so Core 1 chime + SPI e-paper refresh never starve I2S RX DMA
    );
    if (rc != pdPASS) {
        s_ptt_task_running = false;
        s_ptt_task_handle = nullptr;
        return false;
    }
    return true;
}

void stopAsyncPttTask() {
    if (!s_ptt_task_running) return;
    s_ptt_task_running = false;
    while (s_ptt_task_handle != nullptr) {
        delay(1);
    }
}

size_t getRecordedSamples() {
    return s_rec_samples;
}

uint32_t getRecordedMs() {
    return (uint32_t)((s_rec_samples * 1000ULL) / REC_SAMPLE_RATE);
}

float getRecentRms(size_t window_samples) {
    size_t n = s_rec_samples;
    if (!s_wav_buf || n == 0 || window_samples == 0) return 0.0f;
    size_t count = n < window_samples ? n : window_samples;
    size_t start = n - count;
    const int16_t* pcm = reinterpret_cast<const int16_t*>(s_wav_buf + WAV_HEADER_SIZE);
    double sum_sq = 0.0;
    for (size_t i = start; i < n; ++i) {
        double v = pcm[i] / 32768.0;
        sum_sq += v * v;
    }
    return sqrtf((float)(sum_sq / count));
}

WavView finishPttRecording() {
    size_t n = s_rec_samples;
    uint32_t pcm_bytes = n * sizeof(int16_t);
    writeWavHeader(s_wav_buf, pcm_bytes, REC_SAMPLE_RATE);

    const int16_t* pcm = reinterpret_cast<const int16_t*>(s_wav_buf + WAV_HEADER_SIZE);
    double sum_sq = 0.0;
    for (size_t i = 0; i < n; ++i) {
        double v = pcm[i] / 32768.0;
        sum_sq += v * v;
    }
    float rms = n > 0 ? sqrtf((float)(sum_sq / n)) : 0.0f;
    return WavView{s_wav_buf, WAV_HEADER_SIZE + pcm_bytes, rms};
}

WavView buildSilentWav(uint32_t duration_ms) {
    if (!s_wav_buf) return WavView{nullptr, 0, 0.0f};
    size_t samples = (REC_SAMPLE_RATE * duration_ms) / 1000;
    if (samples > s_max_samples) samples = s_max_samples;
    uint32_t pcm_bytes = samples * sizeof(int16_t);
    memset(s_wav_buf + WAV_HEADER_SIZE, 0, pcm_bytes);
    writeWavHeader(s_wav_buf, pcm_bytes, REC_SAMPLE_RATE);
    return WavView{s_wav_buf, WAV_HEADER_SIZE + pcm_bytes, 0.0f};
}

void setPlaybackAbortCheck(AbortCheckFn fn) {
    s_abort_check = fn;
}

bool playPcmChunk(const int16_t* samples, size_t sample_count, uint32_t sample_rate) {
    if (!samples || sample_count == 0) return true;
    if (sample_rate != s_cur_tx_rate && sample_rate >= 8000 && sample_rate <= 48000) {
        s_cur_tx_rate = sample_rate;
        i2s_set_clk(PORT_I2S_TX, s_cur_tx_rate, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
    }
    i2s_start(PORT_I2S_TX);

    // Stream in 1024-sample (~42 ms @ 24 kHz) slices so Barge-In / Cancel buttons
    // abort speaker output immediately without waiting for a full sentence to finish.
    constexpr size_t SLICE_SAMPLES = 1024;
    size_t offset = 0;
    while (offset < sample_count) {
        if (s_abort_check && s_abort_check()) {
            muteSpeaker();
            return false;
        }
        size_t chunk = (sample_count - offset) < SLICE_SAMPLES ? (sample_count - offset) : SLICE_SAMPLES;
        size_t bytes_written = 0;
        esp_err_t err = i2s_write(
            PORT_I2S_TX,
            samples + offset,
            chunk * sizeof(int16_t),
            &bytes_written,
            pdMS_TO_TICKS(1000)
        );
        if (err != ESP_OK) return false;
        offset += chunk;
    }
    return true;
}

bool playBase64PcmChunk(const char* b64_data, size_t b64_len, uint32_t sample_rate) {
    if (!b64_data || b64_len == 0) return true;
    if (s_abort_check && s_abort_check()) {
        muteSpeaker();
        return false;
    }
    size_t max_out = (b64_len * 3) / 4 + 4;
    uint8_t* decoded = (uint8_t*)(psramFound() ? ps_malloc(max_out) : malloc(max_out));
    if (!decoded) return false;

    size_t out_len = 0;
    int rc = mbedtls_base64_decode(decoded, max_out, &out_len, (const unsigned char*)b64_data, b64_len);
    bool ok = false;
    if (rc == 0 && out_len >= 2) {
        ok = playPcmChunk(reinterpret_cast<const int16_t*>(decoded), out_len / sizeof(int16_t), sample_rate);
    }
    free(decoded);
    return ok;
}

void playChime(const char* kind) {
    const uint32_t sr = 24000;
    const size_t n = sr / 12; // 83 ms per note
    int16_t buf[2000];
    float f1 = 880.0f, f2 = 1320.0f;
    if (strcmp(kind, "ptt_stop") == 0) { f1 = 1320.0f; f2 = 880.0f; }
    else if (strcmp(kind, "error") == 0) { f1 = 330.0f; f2 = 220.0f; }
    else if (strcmp(kind, "snap") == 0) { f1 = 1760.0f; f2 = 2093.0f; }

    AbortCheckFn saved = s_abort_check;
    s_abort_check = nullptr;
    for (float freq : {f1, f2}) {
        for (size_t i = 0; i < n; ++i) {
            float env = 1.0f - ((float)i / (float)n);
            buf[i] = (int16_t)(sinf(2.0f * 3.14159265f * freq * ((float)i / sr)) * 4800.0f * env);
        }
        playPcmChunk(buf, n, sr);
    }
    s_abort_check = saved;
    muteSpeaker();
}

void muteSpeaker() {
    i2s_zero_dma_buffer(PORT_I2S_TX);
    i2s_stop(PORT_I2S_TX);
}

} // namespace gotchi_audio
