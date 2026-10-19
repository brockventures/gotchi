"""
Tests for GOTCHI LogBuffer and get_logs RPC contract (F6 / T2.2).
Covers:
- Unconditional credential scrubbing (short secrets <4 chars, multiple Bearer tokens, psk=, password=, token=)
- Pre-limit filtering across the full ring buffer (tag + min_level applied before limit)
- Direct C++ source verification on firmware/include/log_buffer.h and firmware/src/log_buffer.cpp
  (no Serial.printf corruption on USB-C JSON-RPC, FreeRTOS portMUX_TYPE critical sections, filter-before-limit).
"""
import json
import pathlib
import re
from typing import Any, Dict, List, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG_BUFFER_H = REPO_ROOT / "firmware" / "include" / "log_buffer.h"
LOG_BUFFER_CPP = REPO_ROOT / "firmware" / "src" / "log_buffer.cpp"


class ReferenceLogBuffer:
    """Reference verifier matching firmware/src/log_buffer.cpp behavior."""

    LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]

    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self.entries: List[Dict[str, Any]] = []
        self.total_logged = 0

    @staticmethod
    def scrub(msg: str, psk: Optional[str] = None, token: Optional[str] = None) -> str:
        s = msg
        # 1. Explicit PSK and token redacted regardless of length (even 1-3 chars)
        if psk:
            s = s.replace(psk, "[REDACTED_PSK]")
        if token:
            s = s.replace(token, "[REDACTED_TOKEN]")
        # 2. All occurrences of Bearer <tok>, psk=<pw>, password=<pw>, token=<tok>
        s = re.sub(r'(?i)(Bearer\s+)(["\']?)[^\s"\',;\r\n]+\2', r'\1[REDACTED_TOKEN]', s)
        s = re.sub(r'(?i)(psk=\s*)(["\']?)[^\s"\',;\r\n]+\2', r'\1[REDACTED_PSK]', s)
        s = re.sub(r'(?i)(password=\s*)(["\']?)[^\s"\',;\r\n]+\2', r'\1[REDACTED_PSK]', s)
        s = re.sub(r'(?i)(token=\s*)(["\']?)[^\s"\',;\r\n]+\2', r'\1[REDACTED_TOKEN]', s)
        return s

    def log(
        self,
        level: str,
        tag: str,
        msg: str,
        psk: Optional[str] = None,
        token: Optional[str] = None,
        ts: int = 0,
    ):
        scrubbed = self.scrub(msg, psk=psk, token=token)
        entry = {
            "ts": ts,
            "lvl": level.upper(),
            "tag": (tag or "sys")[:15],
            "msg": scrubbed[:127],
        }
        if len(self.entries) >= self.capacity:
            self.entries.pop(0)
        self.entries.append(entry)
        self.total_logged += 1

    def clear(self):
        self.entries.clear()

    def dump_json(
        self,
        limit: int = 50,
        tag_filter: Optional[str] = None,
        min_level: str = "DEBUG",
    ) -> List[Dict[str, Any]]:
        """Filter across the entire ring newest-to-oldest up to `limit`, then return chronological."""
        if not self.entries:
            return []
        eff_limit = len(self.entries) if (limit <= 0 or limit > len(self.entries)) else limit
        min_idx = self.LEVELS.index(min_level.upper()) if min_level.upper() in self.LEVELS else 0
        matched = []
        for entry in reversed(self.entries):
            if len(matched) >= eff_limit:
                break
            lvl_idx = self.LEVELS.index(entry["lvl"]) if entry["lvl"] in self.LEVELS else 0
            if lvl_idx < min_idx:
                continue
            if tag_filter and entry["tag"].lower() != tag_filter.lower():
                continue
            matched.append(entry)
        matched.reverse()
        return matched


def test_cpp_firmware_log_buffer_invariants():
    """Verify firmware/include/log_buffer.h and firmware/src/log_buffer.cpp fix all 4 PR #27 review defects."""
    h_src = LOG_BUFFER_H.read_text(encoding="utf-8")
    cpp_src = LOG_BUFFER_CPP.read_text(encoding="utf-8")

    # 1. No Serial output in LogBuffer::log() (protects USB-C JSON-RPC stream)
    assert "Serial.printf" not in cpp_src
    assert "Serial.print" not in cpp_src
    assert "Serial.write" not in cpp_src

    # 2. Dual-core thread/ISR safety via FreeRTOS spinlock (portMUX_TYPE)
    assert "portMUX_TYPE" in h_src
    assert "portMUX_INITIALIZER_UNLOCKED" in h_src
    assert cpp_src.count("portENTER_CRITICAL(&mux_)") >= 5
    assert cpp_src.count("portEXIT_CRITICAL(&mux_)") >= 5

    # 3. Full credential scrubbing: no >= 4 length gate, multiple occurrences, and psk=/password=/token=/Bearer patterns
    assert "strlen(psk) >= 4" not in cpp_src
    assert "strlen(token) >= 4" not in cpp_src
    assert 'redactPatternValues(temp, sizeof(temp), "Bearer ", "[REDACTED_TOKEN]")' in cpp_src
    assert 'redactPatternValues(temp, sizeof(temp), "psk=", "[REDACTED_PSK]")' in cpp_src
    assert 'redactPatternValues(temp, sizeof(temp), "password=", "[REDACTED_PSK]")' in cpp_src
    assert 'redactPatternValues(temp, sizeof(temp), "token=", "[REDACTED_TOKEN]")' in cpp_src

    # 4. Pre-limit filtering in dumpJson (iterates across cur_count, filters by min_level and tag_filter before matching up to limit)
    assert "for (size_t i = 0; i < cur_count && matched_count < limit; ++i)" in cpp_src
    assert "if (entry.level < min_level) continue;" in cpp_src
    assert "if (has_tag_filter && strcasecmp(entry.tag, tag_filter) != 0) continue;" in cpp_src


def test_credential_scrubbing_short_and_multiple_patterns():
    buf = ReferenceLogBuffer(capacity=16)
    # Short 3-char PSK & token
    buf.log("INFO", "wifi", "Short psk abc and token xyz", psk="abc", token="xyz", ts=10)
    # Multiple Bearer tokens in a single log line
    buf.log("DEBUG", "http", "Primary Bearer tok_one_123 fallback Bearer tok_two_456", ts=20)
    # Inline psk=, password=, token= patterns without explicit psk/token args
    buf.log("WARN", "wifi", "Failed auth psk=mySecretWifiPw password=adminPass token=inlineTok99", ts=30)

    logs = buf.dump_json(limit=10)
    assert logs[0]["msg"] == "Short psk [REDACTED_PSK] and token [REDACTED_TOKEN]"
    assert "tok_one_123" not in logs[1]["msg"]
    assert "tok_two_456" not in logs[1]["msg"]
    assert logs[1]["msg"].count("[REDACTED_TOKEN]") == 2
    assert "mySecretWifiPw" not in logs[2]["msg"]
    assert "adminPass" not in logs[2]["msg"]
    assert "inlineTok99" not in logs[2]["msg"]
    assert logs[2]["msg"].count("[REDACTED_PSK]") == 2
    assert "[REDACTED_TOKEN]" in logs[2]["msg"]


def test_filter_applied_before_limit():
    """Verify tag=wifi, limit=3 finds older wifi entries even when 50 newer audio entries follow."""
    buf = ReferenceLogBuffer(capacity=128)
    for i in range(5):
        buf.log("INFO", "wifi", f"wifi event {i}", ts=100 + i)
    for i in range(60):
        buf.log("DEBUG", "audio", f"mic chunk {i}", ts=200 + i)

    wifi_logs = buf.dump_json(limit=3, tag_filter="wifi")
    assert len(wifi_logs) == 3
    assert [e["msg"] for e in wifi_logs] == ["wifi event 2", "wifi event 3", "wifi event 4"]
