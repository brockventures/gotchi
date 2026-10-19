// ============================================================================
// GOTCHI Circular Log Ring Buffer (F6 / T2.2) Implementation
// ============================================================================

#include "log_buffer.h"
#include <esp_heap_caps.h>
#include <string.h>
#include <stdio.h>

namespace gotchi_log {

LogBuffer RingLogger(DEFAULT_RING_CAPACITY);

static const char* levelToString(Level level) {
    switch (level) {
        case Level::DEBUG: return "DEBUG";
        case Level::INFO:  return "INFO";
        case Level::WARN:  return "WARN";
        case Level::ERROR: return "ERROR";
        default:           return "INFO";
    }
}

static Level levelFromString(const char* str) {
    if (!str) return Level::DEBUG;
    if (strcasecmp(str, "ERROR") == 0) return Level::ERROR;
    if (strcasecmp(str, "WARN") == 0 || strcasecmp(str, "WARNING") == 0) return Level::WARN;
    if (strcasecmp(str, "INFO") == 0) return Level::INFO;
    return Level::DEBUG;
}

// Case-insensitive substring search and replace helper for scrubbing
void scrubCredentials(char* out, size_t out_size, const char* in, const char* psk, const char* token) {
    if (!out || out_size == 0) return;
    if (!in) {
        out[0] = '\0';
        return;
    }

    // Step 1: Copy with truncation to avoid overflow
    char temp[MAX_MSG_LEN];
    strncpy(temp, in, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    // Step 2: Redact known PSK if provided and non-empty (>=4 chars)
    if (psk && strlen(psk) >= 4) {
        char* pos = nullptr;
        while ((pos = strstr(temp, psk)) != nullptr) {
            size_t psk_len = strlen(psk);
            const char* mask = "[REDACTED_PSK]";
            size_t mask_len = strlen(mask);
            size_t tail_len = strlen(pos + psk_len);
            
            // Check if it fits
            if ((pos - temp) + mask_len + tail_len < sizeof(temp)) {
                memmove(pos + mask_len, pos + psk_len, tail_len + 1);
                memcpy(pos, mask, mask_len);
            } else {
                // If it doesn't fit, truncate cleanly
                strncpy(pos, mask, sizeof(temp) - (pos - temp) - 1);
                temp[sizeof(temp) - 1] = '\0';
                break;
            }
        }
    }

    // Step 3: Redact known Bearer Token if provided and non-empty (>=4 chars)
    if (token && strlen(token) >= 4) {
        char* pos = nullptr;
        while ((pos = strstr(temp, token)) != nullptr) {
            size_t tok_len = strlen(token);
            const char* mask = "[REDACTED_TOKEN]";
            size_t mask_len = strlen(mask);
            size_t tail_len = strlen(pos + tok_len);
            
            if ((pos - temp) + mask_len + tail_len < sizeof(temp)) {
                memmove(pos + mask_len, pos + tok_len, tail_len + 1);
                memcpy(pos, mask, mask_len);
            } else {
                strncpy(pos, mask, sizeof(temp) - (pos - temp) - 1);
                temp[sizeof(temp) - 1] = '\0';
                break;
            }
        }
    }

    // Step 4: Redact generic "Bearer <token>" or "psk=<psk>" patterns
    const char* bearer_prefix = "Bearer ";
    char* bpos = strstr(temp, bearer_prefix);
    if (bpos) {
        char* tok_start = bpos + strlen(bearer_prefix);
        while (*tok_start == ' ') tok_start++;
        char* tok_end = tok_start;
        while (*tok_end && *tok_end != ' ' && *tok_end != '"' && *tok_end != '\r' && *tok_end != '\n') {
            tok_end++;
        }
        if (tok_end > tok_start) {
            const char* mask = "[REDACTED_TOKEN]";
            size_t mask_len = strlen(mask);
            size_t orig_len = tok_end - tok_start;
            size_t tail_len = strlen(tok_end);
            if ((tok_start - temp) + mask_len + tail_len < sizeof(temp)) {
                memmove(tok_start + mask_len, tok_end, tail_len + 1);
                memcpy(tok_start, mask, mask_len);
            }
        }
    }

    // Copy result into `out`
    strncpy(out, temp, out_size - 1);
    out[out_size - 1] = '\0';
}

LogBuffer::LogBuffer(size_t capacity)
    : capacity_(capacity > 0 ? capacity : DEFAULT_RING_CAPACITY) {}

LogBuffer::~LogBuffer() {
    if (entries_) {
        free(entries_);
        entries_ = nullptr;
    }
}

bool LogBuffer::init(bool prefer_psram) {
    if (entries_) return true;

    size_t alloc_bytes = capacity_ * sizeof(LogEntry);
    if (prefer_psram && psramFound()) {
        entries_ = static_cast<LogEntry*>(heap_caps_malloc(alloc_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (entries_) {
            in_psram_ = true;
        }
    }

    if (!entries_) {
        // Fallback to internal RAM
        entries_ = static_cast<LogEntry*>(malloc(alloc_bytes));
        in_psram_ = false;
    }

    if (!entries_) {
        // If allocation failed, try half capacity in internal RAM
        capacity_ = capacity_ / 2;
        if (capacity_ > 0) {
            entries_ = static_cast<LogEntry*>(malloc(capacity_ * sizeof(LogEntry)));
        }
    }

    if (entries_) {
        memset(entries_, 0, capacity_ * sizeof(LogEntry));
        head_ = 0;
        count_ = 0;
        total_logged_ = 0;
        return true;
    }
    return false;
}

void LogBuffer::clear() {
    head_ = 0;
    count_ = 0;
    if (entries_) {
        memset(entries_, 0, capacity_ * sizeof(LogEntry));
    }
}

void LogBuffer::log(Level level, const char* tag, const char* msg, const char* psk, const char* token) {
    if (!entries_) {
        if (!init(true)) return;
    }

    LogEntry& entry = entries_[head_];
    entry.timestamp_ms = millis();
    entry.level = level;

    // Copy tag
    if (tag) {
        strncpy(entry.tag, tag, sizeof(entry.tag) - 1);
        entry.tag[sizeof(entry.tag) - 1] = '\0';
    } else {
        strncpy(entry.tag, "sys", sizeof(entry.tag) - 1);
    }

    // Scrub and store message
    scrubCredentials(entry.message, sizeof(entry.message), msg, psk, token);

    // Advance ring head
    head_ = (head_ + 1) % capacity_;
    if (count_ < capacity_) {
        count_++;
    }
    total_logged_++;

    // Mirror to Serial console for development visibility
    Serial.printf("[%lu][%s][%s] %s\n", (unsigned long)entry.timestamp_ms, levelToString(entry.level), entry.tag, entry.message);
}

void LogBuffer::dumpJson(JsonArray& array, size_t limit, const char* tag_filter, Level min_level) const {
    if (!entries_ || count_ == 0) return;

    if (limit == 0 || limit > count_) {
        limit = count_;
    }

    // Determine starting read index:
    // The most recent entry is at (head_ - 1 + capacity_) % capacity_.
    // To return entries in chronological order (oldest to newest):
    // The oldest entry in the window of `limit` entries is at:
    // start_idx = (head_ - count_ + capacity_) % capacity_ (overall oldest).
    // If we only take `limit` newest, start_idx is:
    size_t start_offset = count_ > limit ? (count_ - limit) : 0;
    size_t start_idx = (head_ - count_ + start_offset + capacity_) % capacity_;

    size_t inspected = 0;
    size_t added = 0;
    size_t scan_count = count_ - start_offset;

    for (size_t i = 0; i < scan_count && added < limit; ++i) {
        size_t idx = (start_idx + i) % capacity_;
        const LogEntry& entry = entries_[idx];

        // Apply filters
        if (entry.level < min_level) continue;
        if (tag_filter && strlen(tag_filter) > 0 && strcasecmp(entry.tag, tag_filter) != 0) {
            continue;
        }

        JsonObject obj = array.add<JsonObject>();
        obj["ts"] = entry.timestamp_ms;
        obj["lvl"] = levelToString(entry.level);
        obj["tag"] = entry.tag;
        obj["msg"] = entry.message;
        added++;
    }
}

} // namespace gotchi_log
