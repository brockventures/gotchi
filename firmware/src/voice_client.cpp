// ============================================================================
// GOTCHI Mirrormere voice client (T3.1) — see include/voice_client.h.
// ============================================================================

#include <WiFi.h>
#include <ArduinoJson.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "voice_client.h"

namespace gotchi_voice {
namespace {

constexpr const char* BOUNDARY         = "----GotchiBoundary7MA4YWxkTrZu0gW";
constexpr size_t      SSE_BUF_BYTES    = 256 * 1024;
constexpr uint32_t    CONNECT_TIMEOUT_MS = 5000;
constexpr uint32_t    IDLE_TIMEOUT_MS  = 60000;
constexpr size_t      UPLOAD_CHUNK     = 1460;
constexpr uint32_t    DEFAULT_RATE_HZ  = 24000;

// Buffered socket reader. When `chunked` is set it strips HTTP chunk framing
// (size line + CRLF after each chunk), so an SSE line that spans a chunk
// boundary stays intact.
class Reader {
public:
    explicit Reader(WiFiClient& c) : c_(c) {}

    void setChunked(bool on) { chunked_ = on; }

    // Next body byte, or -1 on EOF / idle timeout / terminating chunk.
    int next() {
        if (!chunked_) return rawByte();
        while (chunk_left_ == 0) {
            char line[32];
            int n = readLine(line, sizeof(line));
            if (n < 0) return -1;
            if (n == 0) continue;           // CRLF that follows a chunk's data
            unsigned long size = strtoul(line, nullptr, 16);
            if (size == 0) return -1;       // last-chunk
            chunk_left_ = size;
        }
        int b = rawByte();
        if (b >= 0) chunk_left_--;
        return b;
    }

    // Reads one raw line (CR stripped) into out, NUL-terminated, truncated to cap-1.
    // Returns stored length, or -1 on EOF / idle timeout.
    int readLine(char* out, size_t cap) {
        size_t len = 0;
        while (true) {
            int b = rawByte();
            if (b < 0) return -1;
            if (b == '\n') break;
            if (b == '\r') continue;
            if (len + 1 < cap) out[len++] = (char)b;
        }
        out[len] = '\0';
        return (int)len;
    }

private:
    int rawByte() {
        if (pos_ == len_ && !fill()) return -1;
        return buf_[pos_++];
    }

    bool fill() {
        uint32_t t0 = millis();
        while (true) {
            int avail = c_.available();
            if (avail > 0) {
                size_t want = (size_t)avail < sizeof(buf_) ? (size_t)avail : sizeof(buf_);
                int got = c_.read(buf_, want);
                if (got <= 0) return false;
                len_ = (size_t)got;
                pos_ = 0;
                return true;
            }
            if (!c_.connected()) return false;
            if (millis() - t0 > IDLE_TIMEOUT_MS) return false;
            delay(1);
        }
    }

    WiFiClient& c_;
    bool chunked_ = false;
    size_t chunk_left_ = 0;
    uint8_t buf_[512];
    size_t pos_ = 0;
    size_t len_ = 0;
};

// Splits "http://host[:port]/path". Only plain http is supported.
bool parseUrl(const String& url, String& host, uint16_t& port, String& path) {
    if (!url.startsWith("http://")) return false;
    String rest = url.substring(7);
    int slash = rest.indexOf('/');
    String hostport = slash < 0 ? rest : rest.substring(0, slash);
    path = slash < 0 ? String("/") : rest.substring(slash);
    int colon = hostport.indexOf(':');
    if (colon < 0) {
        host = hostport;
        port = 80;
    } else {
        host = hostport.substring(0, colon);
        port = (uint16_t)hostport.substring(colon + 1).toInt();
    }
    return host.length() > 0 && port > 0;
}

// Blocking write of n bytes; gives up if the peer goes away or stalls for IDLE_TIMEOUT_MS.
bool writeAll(WiFiClient& c, const uint8_t* p, size_t n) {
    size_t sent = 0;
    uint32_t t0 = millis();
    while (sent < n) {
        size_t w = c.write(p + sent, n - sent);
        if (w == 0) {
            if (!c.connected() || millis() - t0 > IDLE_TIMEOUT_MS) return false;
            delay(1);
            continue;
        }
        sent += w;
        t0 = millis();
    }
    return true;
}

bool containsIgnoreCase(const char* hay, const char* needle) {
    size_t n = strlen(needle);
    for (; *hay; hay++) {
        if (strncasecmp(hay, needle, n) == 0) return true;
    }
    return false;
}

// Pre-stream HTTP status -> device sprite state (docs/MIRRORMERE_VOICE_CLIENT.md).
UiState stateForHttpStatus(int code) {
    switch (code) {
        case 409: return UiState::BUSY;     // another interaction in flight
        case 503: return UiState::OFFLINE;  // hub disabled / inference worker down
        case 400:                           // bad or missing audio
        case 500:                           // pipeline error
        default:  return UiState::ERROR;
    }
}

void setFailure(GotchiUIState& ui, UiState s, const char* code, const String& text, StateCb cb) {
    ui.state = s;
    ui.error_code = code;
    ui.status_text = text;
    if (cb) cb(ui);
}

// Locates the base64 value of "<key>":"...". Works on the raw line so the big
// string is never copied. Value ends at the next '"' (base64 has no escapes).
const char* findB64(const char* line, const char* key, size_t& out_len) {
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\":\"", key);
    const char* p = strstr(line, pat);
    if (!p) {
        snprintf(pat, sizeof(pat), "\"%s\": \"", key);
        p = strstr(line, pat);
    }
    if (!p) return nullptr;
    p += strlen(pat);
    const char* end = strchr(p, '"');
    if (!end) return nullptr;
    out_len = (size_t)(end - p);
    return p;
}

// Handles one `data:` line. Returns true when the event is `done`.
bool handleEvent(const char* event, const char* line, const JsonDocument& filter,
                 GotchiUIState& ui, StateCb cb) {
    const bool is_sentence = strcmp(event, "sentence") == 0;
    const bool is_legacy   = strcmp(event, "audio_chunk") == 0;

    // Audio payload is found by string search first; the JSON pass below skips it.
    size_t b64_len = 0;
    const char* b64 = nullptr;
    if (is_sentence)    b64 = findB64(line, "audio_b64", b64_len);
    else if (is_legacy) b64 = findB64(line, "data", b64_len);

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, line, DeserializationOption::Filter(filter));
    if (err) {
        Serial.printf("voice: bad JSON in '%s' event: %s\n", event, err.c_str());
        return false;
    }

    if (strcmp(event, "state") == 0) {
        UiState next = uiStateFromString(doc["state"] | "");
        const char* name = UI_STATE_NAMES[static_cast<uint8_t>(next)];
        String text = name;
        text.toUpperCase();
        ui.status_text = text;
        if (next != ui.state) {
            ui.state = next;
            if (cb) cb(ui);
        }
    } else if (strcmp(event, "transcript") == 0) {
        const char* t = doc["transcript"] | "";
        if (!*t) t = doc["text"] | "";
        ui.transcript = t;
        ui.status_text = "HEARD";
        if (cb) cb(ui);
    } else if (strcmp(event, "status") == 0) {
        const char* s = doc["status"] | "";
        if (*s) ui.status_text = s;
    } else if (strcmp(event, "reply") == 0) {
        ui.reply = doc["reply"] | "";
        if (cb) cb(ui);
    } else if (is_sentence || is_legacy) {
        if (!b64 || b64_len < 4) {
            Serial.printf("voice: '%s' event without audio payload\n", event);
            return false;
        }
        uint32_t rate = doc["sample_rate"] | DEFAULT_RATE_HZ;
        size_t pad = (b64[b64_len - 1] == '=') + (b64_len >= 2 && b64[b64_len - 2] == '=');
        ui.audio_bytes_received += (uint32_t)((b64_len / 4) * 3 - pad);
        ui.last_sample_rate = rate;
        if (ui.state != UiState::SPEAKING) {
            ui.state = UiState::SPEAKING;
            if (cb) cb(ui);
        }
        gotchi_audio::playBase64PcmChunk(b64, b64_len, rate);
    } else if (strcmp(event, "error") == 0) {
        const char* code = doc["error"] | "error";
        const char* msg  = doc["message"] | "";
        ui.state = UiState::ERROR;
        ui.error_code = code;
        if (*msg) ui.status_text = String(msg).substring(0, 22);
        if (cb) cb(ui);
    } else if (strcmp(event, "done") == 0) {
        return true;
    }
    // `turn` and unknown events are ignored.
    return false;
}

// Reads SSE lines from rd into buf. Returns true if `done` was seen.
bool streamEvents(Reader& rd, char* buf, GotchiUIState& ui, StateCb cb) {
    // Allow-list filter: only small scalar keys are kept. audio_b64 / data are
    // not in the list, so they are skipped during parsing and never copied.
    JsonDocument filter;
    filter["state"] = true;
    filter["transcript"] = true;
    filter["text"] = true;
    filter["status"] = true;
    filter["reply"] = true;
    filter["sample_rate"] = true;
    filter["error"] = true;
    filter["message"] = true;

    char event[24] = "";
    size_t len = 0;
    bool overflow = false;
    while (true) {
        int b = rd.next();
        if (b < 0) return false;            // EOF or idle timeout before `done`
        if (b == '\r') continue;
        if (b != '\n') {
            if (len < SSE_BUF_BYTES - 1) buf[len++] = (char)b;
            else overflow = true;
            continue;
        }

        buf[len] = '\0';
        if (overflow) {
            // Line is larger than the buffer: drop it, never write past the end.
            Serial.printf("voice: dropped SSE line over %u bytes (event '%s')\n",
                          (unsigned)SSE_BUF_BYTES, event);
        } else if (len == 0) {
            event[0] = '\0';                // blank line ends the event block
        } else if (strncmp(buf, "event:", 6) == 0) {
            const char* name = buf + 6;
            while (*name == ' ') name++;
            strncpy(event, name, sizeof(event) - 1);
            event[sizeof(event) - 1] = '\0';
        } else if (strncmp(buf, "data:", 5) == 0) {
            if (handleEvent(event, buf + 5, filter, ui, cb)) return true;
        }
        len = 0;
        overflow = false;
    }
}

} // namespace

bool interact(const gotchi_audio::WavView& wav, const String& url, const String& node_id,
              GotchiUIState& ui, StateCb cb, const String& bearer_token) {
    String host, path;
    uint16_t port = 80;
    if (!parseUrl(url, host, port, path) || !wav.data || wav.length == 0) {
        setFailure(ui, UiState::ERROR, "bad_url", "BAD VOICE URL", cb);
        return false;
    }
    if (WiFi.status() != WL_CONNECTED) {
        setFailure(ui, UiState::OFFLINE, "wifi", "NO WIFI", cb);
        return false;
    }

    // multipart/form-data body = pre + WAV + post (matches poc build_multipart_wav).
    char session[24];
    snprintf(session, sizeof(session), "gotchi-%lu", (unsigned long)millis());

    String pre;
    pre += "--";
    pre += BOUNDARY;
    pre += "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"ptt.wav\"\r\n";
    pre += "Content-Type: audio/wav\r\n\r\n";

    String post = "\r\n--";
    post += BOUNDARY;
    post += "\r\nContent-Disposition: form-data; name=\"node_id\"\r\n\r\n";
    post += node_id;
    post += "\r\n--";
    post += BOUNDARY;
    post += "\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n";
    post += session;
    post += "\r\n--";
    post += BOUNDARY;
    post += "--\r\n";

    size_t content_len = pre.length() + wav.length + post.length();

    String head = "POST " + path + " HTTP/1.1\r\n";
    head += "Host: " + host;
    if (port != 80) head += ":" + String(port);
    head += "\r\n";
    head += "Content-Type: multipart/form-data; boundary=";
    head += BOUNDARY;
    head += "\r\n";
    head += "Content-Length: " + String((unsigned long)content_len) + "\r\n";
    head += "Accept: text/event-stream\r\n";
    head += "X-Gotchi-Node: " + node_id + "\r\n";
    if (bearer_token.length() > 0) {
        head += "Authorization: Bearer " + bearer_token + "\r\n";
    }
    head += "Connection: close\r\n\r\n";

    WiFiClient client;
    if (!client.connect(host.c_str(), port, CONNECT_TIMEOUT_MS)) {
        setFailure(ui, UiState::OFFLINE, "connect", "NO HUB", cb);
        return false;
    }

    bool sent = writeAll(client, (const uint8_t*)head.c_str(), head.length())
             && writeAll(client, (const uint8_t*)pre.c_str(), pre.length());
    for (size_t off = 0; sent && off < wav.length; off += UPLOAD_CHUNK) {
        size_t n = wav.length - off < UPLOAD_CHUNK ? wav.length - off : UPLOAD_CHUNK;
        sent = writeAll(client, wav.data + off, n);
    }
    sent = sent && writeAll(client, (const uint8_t*)post.c_str(), post.length());
    if (!sent) {
        client.stop();
        setFailure(ui, UiState::ERROR, "send", "UPLOAD FAILED", cb);
        return false;
    }

    Reader rd(client);
    char line[256];
    int n = rd.readLine(line, sizeof(line));
    if (n < 0) {
        client.stop();
        setFailure(ui, UiState::ERROR, "no_response", "NO RESPONSE", cb);
        return false;
    }
    int status = 0;
    if (strncmp(line, "HTTP/", 5) == 0) {
        const char* sp = strchr(line, ' ');
        if (sp) status = atoi(sp + 1);
    }
    if (status != 200) {
        // Pre-stream error: JSON body follows; the status is all we act on.
        client.stop();
        char code[8];
        snprintf(code, sizeof(code), "%d", status);
        setFailure(ui, stateForHttpStatus(status), code, String("HTTP ") + code, cb);
        return false;
    }

    bool chunked = false;
    while (true) {
        n = rd.readLine(line, sizeof(line));
        if (n < 0) {
            client.stop();
            setFailure(ui, UiState::ERROR, "headers", "BAD RESPONSE", cb);
            return false;
        }
        if (n == 0) break;
        if (strncasecmp(line, "Transfer-Encoding:", 18) == 0 && containsIgnoreCase(line, "chunked")) {
            chunked = true;
        }
    }
    rd.setChunked(chunked);

    char* buf = (char*)ps_malloc(SSE_BUF_BYTES);
    if (!buf) {
        client.stop();
        setFailure(ui, UiState::ERROR, "oom", "NO PSRAM", cb);
        return false;
    }

    bool done = streamEvents(rd, buf, ui, cb);

    free(buf);
    gotchi_audio::muteSpeaker();
    client.stop();
    return done;
}

} // namespace gotchi_voice
