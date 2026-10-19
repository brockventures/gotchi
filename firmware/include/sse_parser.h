#pragma once
// ============================================================================
// GOTCHI — Pure SSE line parser (text/event-stream). Host-testable: no Arduino.
// Port of the line handling in poc/gotchi_poc.py `parse_sse_stream`:
//   - bytes accumulate into a line buffer; a line ends at '\n' (trailing '\r' stripped)
//   - `event:` sets the event name (leading/trailing spaces trimmed)
//   - `data:` appends to the data, multiple data lines joined with '\n'
//   - a blank line emits the event if a name is set, then resets
//   - all other lines (id:, retry:, comments) are ignored
// ============================================================================

#include <cstddef>
#include <functional>
#include <string>

namespace gotchi_sse {

struct Event {
    std::string name;
    std::string data;
};

class Parser {
public:
    using Handler = std::function<void(const Event&)>;

    void feed(const char* chunk, size_t len, const Handler& onEvent) {
        for (size_t i = 0; i < len; ++i) {
            if (chunk[i] == '\n') {
                processLine(onEvent);
            } else {
                line_.push_back(chunk[i]);
            }
        }
    }

    // End of stream: process an unterminated last line, then emit a pending named event.
    // Matches the final flush_event() call in parse_sse_stream.
    void finish(const Handler& onEvent) {
        if (!line_.empty()) processLine(onEvent);
        if (!name_.empty()) emit(onEvent);
    }

private:
    static std::string trim(const std::string& s) {
        size_t b = s.find_first_not_of(" \t");
        if (b == std::string::npos) return std::string();
        size_t e = s.find_last_not_of(" \t");
        return s.substr(b, e - b + 1);
    }

    void emit(const Handler& onEvent) {
        Event ev{name_, data_};
        name_.clear();
        data_.clear();
        has_data_ = false;
        onEvent(ev);
    }

    void processLine(const Handler& onEvent) {
        if (!line_.empty() && line_.back() == '\r') line_.pop_back();

        if (line_.empty()) {
            if (!name_.empty()) {
                emit(onEvent);
            } else {
                data_.clear();
                has_data_ = false;
            }
            line_.clear();
            return;
        }

        if (line_.compare(0, 6, "event:") == 0) {
            name_ = trim(line_.substr(6));
        } else if (line_.compare(0, 5, "data:") == 0) {
            std::string value = line_.substr(5);
            if (!value.empty() && value[0] == ' ') value.erase(0, 1);
            if (has_data_) data_ += '\n';
            data_ += value;
            has_data_ = true;
        }
        line_.clear();
    }

    std::string line_;
    std::string name_;
    std::string data_;
    bool has_data_ = false;
};

} // namespace gotchi_sse
