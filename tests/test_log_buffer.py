"""
Tests for GOTCHI LogBuffer and get_logs RPC contract (F6 / T2.2).
"""
import json
import re
from typing import List, Dict, Any, Optional

class MockLogBuffer:
    """Python reference implementation and test harness for gotchi_log::LogBuffer."""
    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self.entries: List[Dict[str, Any]] = []
        self.total_logged = 0

    def scrub(self, msg: str, psk: Optional[str] = None, token: Optional[str] = None) -> str:
        s = msg
        if psk and len(psk) >= 4:
            s = s.replace(psk, "[REDACTED_PSK]")
        if token and len(token) >= 4:
            s = s.replace(token, "[REDACTED_TOKEN]")
        # Generic Bearer scrub
        s = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED_TOKEN]', s)
        return s

    def log(self, level: str, tag: str, msg: str, psk: Optional[str] = None, token: Optional[str] = None, ts: int = 0):
        scrubbed = self.scrub(msg, psk=psk, token=token)
        entry = {
            "ts": ts,
            "lvl": level.upper(),
            "tag": tag[:15],
            "msg": scrubbed[:127]
        }
        if len(self.entries) >= self.capacity:
            self.entries.pop(0)
        self.entries.append(entry)
        self.total_logged += 1

    def clear(self):
        self.entries.clear()

    def get_logs(self, limit: int = 50, tag: Optional[str] = None, min_lvl: Optional[str] = None) -> List[Dict[str, Any]]:
        res = list(self.entries)
        if min_lvl:
            lvls = ["DEBUG", "INFO", "WARN", "ERROR"]
            min_idx = lvls.index(min_lvl.upper()) if min_lvl.upper() in lvls else 0
            res = [e for e in res if lvls.index(e["lvl"]) >= min_idx]
        if tag:
            res = [e for e in res if e["tag"].lower() == tag.lower()]
        if limit > 0 and len(res) > limit:
            res = res[-limit:]
        return res

def handle_rpc_mock(req_json: str, log_buffer: MockLogBuffer, cfg: Dict[str, Any]) -> str:
    req = json.loads(req_json)
    cmd = req.get("cmd", "")
    res = {"cmd": cmd, "ok": True}

    if cmd == "get_logs":
        limit = req.get("limit", req.get("lines", 50))
        tag = req.get("tag")
        min_lvl = req.get("level")
        res["total_logged"] = log_buffer.total_logged
        res["count"] = len(log_buffer.entries)
        res["capacity"] = log_buffer.capacity
        res["logs"] = log_buffer.get_logs(limit=limit, tag=tag, min_lvl=min_lvl)
    elif cmd == "clear_logs":
        log_buffer.clear()
        res["status"] = "cleared"
    else:
        res["ok"] = False
        res["error"] = "unknown_command"
    return json.dumps(res)


def test_log_buffer_ring_wrapping():
    buf = MockLogBuffer(capacity=5)
    for i in range(10):
        buf.log("INFO", "boot", f"event {i}", ts=1000 + i * 100)
    
    assert buf.total_logged == 10
    assert len(buf.entries) == 5
    logs = buf.get_logs(limit=5)
    assert len(logs) == 5
    assert logs[0]["msg"] == "event 5"
    assert logs[-1]["msg"] == "event 9"


def test_credential_scrubbing():
    buf = MockLogBuffer(capacity=10)
    buf.log("INFO", "wifi", "Connecting to AP with psk=SecretPsk123", psk="SecretPsk123", ts=100)
    buf.log("INFO", "http", "POST /interact Authorization: Bearer DeviceTokenSecret456", token="DeviceTokenSecret456", ts=110)
    buf.log("DEBUG", "http", "Headers: Bearer some_random_tunnel_jwt_token_here", ts=120)

    logs = buf.get_logs()
    assert "SecretPsk123" not in logs[0]["msg"]
    assert "[REDACTED_PSK]" in logs[0]["msg"]
    assert "DeviceTokenSecret456" not in logs[1]["msg"]
    assert "[REDACTED_TOKEN]" in logs[1]["msg"]
    assert "some_random_tunnel_jwt_token_here" not in logs[2]["msg"]
    assert "[REDACTED_TOKEN]" in logs[2]["msg"]


def test_get_logs_rpc_dispatch():
    buf = MockLogBuffer(capacity=50)
    buf.log("INFO", "boot", "Booting ESP32S3 FW 0.1.0", ts=10)
    buf.log("WARN", "epd", "BUSY wait slow", ts=20)
    buf.log("ERROR", "wifi", "Connection timeout", ts=30)

    # Test default get_logs
    raw = handle_rpc_mock('{"cmd": "get_logs"}', buf, {})
    res = json.loads(raw)
    assert res["ok"] is True
    assert res["cmd"] == "get_logs"
    assert res["count"] == 3
    assert len(res["logs"]) == 3

    # Test lines parameter compatibility (per ARCHITECTURE.md)
    raw_lines = handle_rpc_mock('{"cmd": "get_logs", "lines": 2}', buf, {})
    res_lines = json.loads(raw_lines)
    assert len(res_lines["logs"]) == 2
    assert res_lines["logs"][0]["tag"] == "epd"
    assert res_lines["logs"][1]["tag"] == "wifi"

    # Test clear_logs
    raw_clear = handle_rpc_mock('{"cmd": "clear_logs"}', buf, {})
    res_clear = json.loads(raw_clear)
    assert res_clear["ok"] is True
    assert res_clear["status"] == "cleared"

    raw_empty = handle_rpc_mock('{"cmd": "get_logs"}', buf, {})
    res_empty = json.loads(raw_empty)
    assert res_empty["count"] == 0
    assert len(res_empty["logs"]) == 0
