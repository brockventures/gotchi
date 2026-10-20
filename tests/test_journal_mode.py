"""Unit and contract tests for V1 All-Day Journal Mode & BLE Low-Power State (F24 / T3.5)."""

import struct
from pathlib import Path

from fastapi.testclient import TestClient

from backend.journal_service import JournalService, extract_followup_tasks
from backend.voice_gateway import VoiceGatewayService, create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_voiced_wav(duration_ms: int = 800, sample_rate: int = 16000, amplitude: int = 3000) -> bytes:
    num_samples = int((sample_rate * duration_ms) / 1000)
    pcm = struct.pack(f"<{num_samples}h", *([amplitude, -amplitude] * (num_samples // 2)))
    riff_size = 36 + len(pcm)
    byte_rate = sample_rate * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        byte_rate,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


def test_extract_followup_tasks_deduplicates_and_categorizes():
    transcript = (
        "Great meeting with Mike. Remind me to order the M2 brass standoffs before Friday. "
        "We need to measure the D4 idle voltage on the bench. "
        "Also remind me to order the M2 brass standoffs before Friday! "
        "Follow up with Alex on the enclosure step file."
    )
    tasks = extract_followup_tasks(transcript)
    assert len(tasks) == 3
    assert tasks[0]["category"] == "reminder"
    assert "Order the M2 brass standoffs before Friday" in tasks[0]["title"]
    assert tasks[1]["category"] == "todo"
    assert "Measure the D4 idle voltage on the bench" in tasks[1]["title"]
    assert tasks[2]["category"] == "followup"
    assert "Alex on the enclosure step file" in tasks[2]["title"]


def test_journal_service_episode_stitching_and_ghost_filtering():
    svc = JournalService(min_voiced_ms=400, episode_gap_s=300.0)
    wav = _build_voiced_wav(duration_ms=800)

    # 1. Ghost phrase should be filtered out cleanly
    g_res = svc.ingest_segment(
        node_id="gotchi-v1-01",
        audio_bytes=wav,
        transcript="Thank you for watching.",
        timestamp_s=1000.0,
    )
    assert g_res["ghost_filtered"] is True
    assert svc.get_journal("gotchi-v1-01")["segment_count"] == 0

    # 2. Two segments 60s apart stitch into the same episode and extract tasks
    r1 = svc.ingest_segment(
        node_id="gotchi-v1-01",
        audio_bytes=wav,
        transcript="Discussing V1 battery life. Remind me to test BLE-only current draw.",
        timestamp_s=1000.0,
    )
    r2 = svc.ingest_segment(
        node_id="gotchi-v1-01",
        audio_bytes=wav,
        transcript="We need to verify 80 MHz CPU clock with WiFi off.",
        timestamp_s=1060.0,
    )
    assert r1["episode_id"] == r2["episode_id"]

    # 3. Segment 600s later (> 300s gap) starts a second episode
    r3 = svc.ingest_segment(
        node_id="gotchi-v1-01",
        audio_bytes=wav,
        transcript="Afternoon sync. I'll send the updated BOM spreadsheet tonight.",
        timestamp_s=1700.0,
    )
    assert r3["episode_id"] != r1["episode_id"]

    summary = svc.summarize_day("gotchi-v1-01")
    assert summary["episode_count"] == 2
    assert summary["open_task_count"] == 3
    task_id = summary["tasks"][0]["task_id"]

    updated = svc.update_task_status("gotchi-v1-01", task_id, "done")
    assert updated["task"]["status"] == "done"
    assert svc.summarize_day("gotchi-v1-01")["open_task_count"] == 2


def test_gateway_journal_http_and_ble_interact_routes():
    app = create_app(VoiceGatewayService(auth_required=False))
    client = TestClient(app)
    wav = _build_voiced_wav(duration_ms=800)

    # 1. Direct POST /api/journal/ingest (multipart)
    resp = client.post(
        "/api/journal/ingest",
        data={
            "node_id": "gotchi-v1-01",
            "transcript": "Remind me to pack the USB-C power meter for the bench test.",
        },
        files={"audio": ("journal.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["ghost_filtered"] is False
    assert len(body["tasks_extracted"]) == 1

    # 2. BLE / Wi-Fi POST /api/voice/interact with mode="journal"
    resp2 = client.post(
        "/api/voice/interact",
        data={
            "node_id": "gotchi-v1-01",
            "mode": "journal",
            "prompt": "We need to print the back shell in matte PETG.",
        },
        files={"audio": ("journal.wav", wav, "audio/wav")},
    )
    assert resp2.status_code == 200
    assert "event: done" in resp2.text
    assert "journal_logged" in resp2.text

    # 3. Query GET /api/journal/entries & POST /api/journal/summarize
    entries = client.get("/api/journal/entries", params={"node_id": "gotchi-v1-01"}).json()
    assert entries["segment_count"] == 2
    assert entries["episode_count"] == 1
    assert len(entries["tasks"]) == 2

    sum_resp = client.post("/api/journal/summarize", json={"node_id": "gotchi-v1-01"}).json()
    assert sum_resp["ok"] is True
    assert sum_resp["open_task_count"] == 2


def test_firmware_journal_mode_and_ble_low_power_contracts():
    main_cpp = (REPO_ROOT / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    vc_h = (REPO_ROOT / "firmware" / "include" / "voice_client.h").read_text(encoding="utf-8")
    vc_cpp = (REPO_ROOT / "firmware" / "src" / "voice_client.cpp").read_text(encoding="utf-8")

    # Config defaults to off (false) and exposes JSON-RPC + NVS persistence
    assert "bool     journal_mode = false;" in main_cpp
    assert "bool     ble_disable_wifi = true;" in main_cpp
    assert 'res["journal_mode"] = cfg.journal_mode;' in main_cpp
    assert 'res["ble_disable_wifi"] = cfg.ble_disable_wifi;' in main_cpp
    assert 'if (req["journal_mode"].is<bool>()) cfg.journal_mode = req["journal_mode"].as<bool>();' in main_cpp
    assert 'if (req["ble_disable_wifi"].is<bool>()) cfg.ble_disable_wifi = req["ble_disable_wifi"].as<bool>();' in main_cpp

    # BLE-connected default behavior turns off Wi-Fi and drops CPU clock to 80 MHz
    assert "manageBleLowPowerWiFi()" in main_cpp
    assert "bool want_ble_lp = cfg.ble_disable_wifi && gotchi_ble::isBlePeerConnected();" in main_cpp
    assert "WiFi.mode(WIFI_OFF);" in main_cpp
    assert "setCpuFrequencyMhz(80);" in main_cpp
    assert "if (WiFi.status() != WL_CONNECTED && !gotchi_ble::isBlePeerConnected())" in main_cpp

    # Passive journal loop & upload helper
    assert "pollJournalMode()" in main_cpp
    assert "uploadJournalSegment" in vc_h
    assert 'commitDoc["mode"] = "journal";' in vc_cpp
