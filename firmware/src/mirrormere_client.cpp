#include "mirrormere_client.h"
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <string.h>

namespace gotchi_hub {

static constexpr char     MULTIPART_BOUNDARY[] = "----gotchiboundary";
static constexpr uint32_t HTTP_TIMEOUT_MS      = 60000;
static constexpr uint32_t DEFAULT_SAMPLE_RATE  = 24000;
static constexpr size_t   STREAM_BUF_BYTES     = 512;

// ---------------------------------------------------------------------------
// SseParser wrapper
// ---------------------------------------------------------------------------

static SseEvent toSseEvent(const gotchi_sse::Event& ev) {
    SseEvent out;
    out.name = ev.name.c_str();
    out.data = ev.data.c_str();
    return out;
}

void SseParser::feed(const char* chunk, size_t len, std::function<void(const SseEvent&)> onEvent) {
    parser_.feed(chunk, len, [&onEvent](const gotchi_sse::Event& ev) { onEvent(toSseEvent(ev)); });
}

void SseParser::finish(std::function<void(const SseEvent&)> onEvent) {
    parser_.finish([&onEvent](const gotchi_sse::Event& ev) { onEvent(toSseEvent(ev)); });
}

// ---------------------------------------------------------------------------
// Event application (port of flush_event in poc/gotchi_poc.py)
// ---------------------------------------------------------------------------

AudioSink defaultAudioSink() {
    AudioSink sink;
    sink.play = [](const char* b64, size_t b64_len, uint32_t sample_rate) {
        return gotchi_audio::playBase64PcmChunk(b64, b64_len, sample_rate);
    };
    return sink;
}

void applyEvent(const SseEvent& ev, GotchiUIState& ui, AudioSink& sink) {
    JsonDocument doc;
    if (deserializeJson(doc, ev.data.c_str())) return;  // malformed payload: ignore

    if (ev.name == "state") {
        const char* st = doc["state"] | "idle";
        ui.state = uiStateFromString(st);
        ui.status_text = st;
        ui.status_text.toUpperCase();
    } else if (ev.name == "transcript") {
        ui.transcript = doc["transcript"] | "";
        const char* spk = doc["speaker"] | "";
        ui.status_text = spk[0] ? String("HEARD (") + spk + ")" : String("HEARD");
    } else if (ev.name == "status") {
        if (doc["status"].is<const char*>()) ui.status_text = doc["status"].as<const char*>();
    } else if (ev.name == "thinking") {
        uint16_t secs = doc["elapsed_seconds"] | 0;
        ui.state = UiState::THINKING;
        ui.thinking_seconds = secs;
        ui.status_text = String("THINKING (") + secs + "s)";
    } else if (ev.name == "reply") {
        ui.reply = doc["reply"] | "";
        ui.status_text = "SPEAKING";
    } else if (ev.name == "audio_chunk") {
        ui.state = UiState::SPEAKING;
        const char* b64 = doc["data"] | "";
        size_t b64_len = strlen(b64);
        uint32_t sr = doc["sample_rate"] | 0;
        if (sr == 0) sr = DEFAULT_SAMPLE_RATE;
        ui.audio_bytes_received += (uint32_t)(b64_len * 3 / 4);
        ui.last_sample_rate = sr;
        if (sink.play && b64_len > 0) sink.play(b64, b64_len, sr);
    } else if (ev.name == "error") {
        ui.state = UiState::ERROR;
        ui.error_code = doc["error"] | "error";
        String msg = doc["message"] | "";
        if (msg.isEmpty()) msg = ui.error_code;
        ui.status_text = msg.substring(0, 22);
    } else if (ev.name == "done") {
        uint32_t dur = doc["duration_ms"] | 0;
        ui.state = UiState::IDLE;
        ui.status_text = String("DONE (") + dur + "ms)";
    }
}

// ---------------------------------------------------------------------------
// interact()
// ---------------------------------------------------------------------------

static uint8_t* allocBody(size_t n) {
    uint8_t* p = (uint8_t*)ps_malloc(n);
    if (!p) p = (uint8_t*)malloc(n);
    return p;
}

InteractResult interact(const String& hub_url, const String& node_id, const gotchi_audio::WavView& wav,
                        GotchiUIState& ui, std::function<void(const GotchiUIState&)> onUi) {
    // 1. Multipart body: audio part (WAV, already includes its 44-byte header) + node_id part.
    String head = String("--") + MULTIPART_BOUNDARY +
                  "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"ptt.wav\"\r\n"
                  "Content-Type: audio/wav\r\n\r\n";
    String tail = String("\r\n--") + MULTIPART_BOUNDARY +
                  "\r\nContent-Disposition: form-data; name=\"node_id\"\r\n\r\n" + node_id +
                  "\r\n--" + MULTIPART_BOUNDARY + "--\r\n";
    size_t total = head.length() + wav.length + tail.length();

    uint8_t* body = allocBody(total);
    if (!body) {
        ui.state = UiState::ERROR;
        ui.error_code = "oom";
        return InteractResult::NETWORK_ERROR;
    }
    memcpy(body, head.c_str(), head.length());
    memcpy(body + head.length(), wav.data, wav.length);
    memcpy(body + head.length() + wav.length, tail.c_str(), tail.length());

    // 2. POST. HTTP/1.0 so the response is not chunk-framed; the raw stream is then pure SSE.
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.useHTTP10(true);
    String url = hub_url + "/api/voice/interact";
    if (!http.begin(url)) {
        free(body);
        ui.state = UiState::ERROR;
        ui.error_code = "network";
        return InteractResult::NETWORK_ERROR;
    }
    http.addHeader("Content-Type", String("multipart/form-data; boundary=") + MULTIPART_BOUNDARY);
    int code = http.POST(body, total);
    free(body);  // body is fully written by POST(); free on every path below too

    // 3. Status handling.
    if (code < 0) {
        http.end();
        ui.state = UiState::ERROR;
        ui.error_code = "network";
        return InteractResult::NETWORK_ERROR;
    }
    switch (code) {
        case 200:
            break;
        case 400:
            http.end();
            ui.state = UiState::ERROR;
            ui.error_code = "bad_audio";
            return InteractResult::HTTP_400;
        case 409:
            http.end();
            ui.state = UiState::BUSY;
            ui.error_code = "busy";
            return InteractResult::HTTP_409;
        case 500:
            http.end();
            ui.state = UiState::ERROR;
            ui.error_code = "hub_error";
            return InteractResult::HTTP_500;
        case 503:
            http.end();
            ui.state = UiState::OFFLINE;
            ui.error_code = "hub_offline";
            return InteractResult::HTTP_503;
        default:
            // Not in the spec's status table; reported as a network-class failure.
            http.end();
            ui.state = UiState::ERROR;
            ui.error_code = String("http_") + code;
            return InteractResult::NETWORK_ERROR;
    }

    // 4. Stream the SSE reply until `done`, stream end, or 60 s of silence.
    WiFiClient* stream = http.getStreamPtr();
    if (!stream) {  // 200 but the connection is already closed: getStreamPtr() returns nullptr
        http.end();
        ui.state = UiState::ERROR;
        ui.error_code = "network";
        return InteractResult::NETWORK_ERROR;
    }
    SseParser parser;
    AudioSink sink = defaultAudioSink();
    bool done = false;
    InteractResult result = InteractResult::OK;

    auto handle = [&](const SseEvent& ev) {
        if (done) return;
        applyEvent(ev, ui, sink);
        if (onUi) onUi(ui);
        if (ev.name == "done") done = true;
    };

    uint8_t buf[STREAM_BUF_BYTES];
    uint32_t last_rx_ms = millis();
    while (!done) {
        int avail = stream->available();
        if (avail > 0) {
            size_t n = stream->readBytes((char*)buf, min((size_t)avail, sizeof(buf)));
            last_rx_ms = millis();
            parser.feed((const char*)buf, n, handle);
            continue;
        }
        if (!http.connected()) break;  // server closed the stream
        if (millis() - last_rx_ms > HTTP_TIMEOUT_MS) {
            result = InteractResult::TIMEOUT;
            ui.state = UiState::ERROR;
            ui.error_code = "timeout";
            break;
        }
        delay(1);  // yield so the watchdog and the HTTP server keep running
    }
    if (result == InteractResult::OK && !done) parser.finish(handle);

    // 5. Done with the connection on every path.
    http.end();
    return result;
}

} // namespace gotchi_hub
