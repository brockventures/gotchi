#pragma once
// ============================================================================
// GOTCHI Circular Log Ring Buffer (F6 / T2.2)
//   - Fixed-capacity circular ring buffer in RAM/PSRAM.
//   - Diagnostic events: boot, wifi, http, audio, camera, epd, error.
//   - Unconditional credential scrubbing: bearer tokens, Wi-Fi PSKs, passwords.
//   - Thread-safe / interrupt-safe logging hooks for dual-transport JSON-RPC.
// ============================================================================

#include <Arduino.h>
#include <ArduinoJson.h>

namespace gotchi_log {

enum class Level : uint8_t {
    DEBUG = 0,
    INFO  = 1,
    WARN  = 2,
    ERROR = 3,
};

// Maximum message length per log entry (bounded memory consumption)
constexpr size_t MAX_MSG_LEN = 128;
constexpr size_t MAX_TAG_LEN = 16;
constexpr size_t DEFAULT_RING_CAPACITY = 128;

struct LogEntry {
    uint32_t timestamp_ms = 0;
    Level level = Level::INFO;
    char tag[MAX_TAG_LEN] = {0};
    char message[MAX_MSG_LEN] = {0};
};

// Redacts sensitive substrings (tokens, PSKs, passwords) from a raw message.
void scrubCredentials(char* out, size_t out_size, const char* in, const char* psk = nullptr, const char* token = nullptr);

class LogBuffer {
public:
    explicit LogBuffer(size_t capacity = DEFAULT_RING_CAPACITY);
    ~LogBuffer();

    // Initializes ring buffer in RAM or PSRAM.
    bool init(bool prefer_psram = true);

    // Records a log entry with timestamp millis() and automatic credential scrubbing.
    void log(Level level, const char* tag, const char* msg, const char* psk = nullptr, const char* token = nullptr);

    void info(const char* tag, const char* msg)  { log(Level::INFO, tag, msg); }
    void warn(const char* tag, const char* msg)  { log(Level::WARN, tag, msg); }
    void error(const char* tag, const char* msg) { log(Level::ERROR, tag, msg); }
    void debug(const char* tag, const char* msg) { log(Level::DEBUG, tag, msg); }

    // Clears all entries from the ring buffer.
    void clear();

    // Returns total count of log events recorded since boot.
    uint32_t totalLogged() const { return total_logged_; }

    // Returns current number of valid entries available in ring (<= capacity).
    size_t count() const { return count_; }

    // Returns capacity of the ring buffer.
    size_t capacity() const { return capacity_; }

    // Serializes up to `limit` latest log entries into an ArduinoJson JsonArray or JsonDocument.
    void dumpJson(JsonArray& array, size_t limit = 50, const char* tag_filter = nullptr, Level min_level = Level::DEBUG) const;

private:
    size_t capacity_ = DEFAULT_RING_CAPACITY;
    LogEntry* entries_ = nullptr;
    size_t head_ = 0; // index where next write occurs
    size_t count_ = 0; // number of elements currently stored
    uint32_t total_logged_ = 0;
    bool in_psram_ = false;
};

// Global singleton instance
extern LogBuffer RingLogger;

} // namespace gotchi_log
