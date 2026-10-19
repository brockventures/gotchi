"""
Tests for GOTCHI Reply Audio Routing Mode (F8 / T3.3).
Covers:
- Direct VoiceGatewayService validation & routing in backend/voice_gateway.py
  (rejecting invalid audio_out_mode with ValueError/400, routing discord_voice & ble_phone chunks via audio_sink_router)
- Firmware C++ source verification on firmware/src/main.cpp (set_config rejects unknown audio_out_mode with ok:false, error:invalid_audio_out_mode)
- Multipart form-data encoding and muted local speaker SSE state synchronization.
"""
import base64
import json
import pathlib
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from backend.voice_gateway import VoiceGatewayService, create_app
from poc.gotchi_poc import (
    build_multipart_wav,
    parse_sse_stream,
    wrap_pcm16_to_wav,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_CPP = REPO_ROOT / "firmware" / "src" / "main.cpp"


def test_firmware_set_config_rejects_invalid_audio_out_mode():
    """Verify firmware/src/main.cpp returns ok:false and error:invalid_audio_out_mode for unknown values."""
    src = MAIN_CPP.read_text(encoding="utf-8")
    assert 'if (m != "speaker" && m != "discord_voice" && m != "ble_phone")' in src
    assert 'res["ok"] = false;' in src
    assert 'res["error"] = "invalid_audio_out_mode";' in src


def test_backend_voice_gateway_routes_and_validates_audio_out_mode():
    """Verify backend/voice_gateway.py validates audio_out_mode and triggers audio_sink_router for non-speaker modes."""
    routed_calls: List[Dict[str, Any]] = []

    def sink_router(mode: str, node_id: str, pcm: bytes, sr: int, text: str):
        routed_calls.append({
            "mode": mode,
            "node_id": node_id,
            "pcm_bytes": len(pcm),
            "sr": sr,
            "text": text,
        })

    srv = VoiceGatewayService(audio_sink_router=sink_router)
    app = create_app(srv)
    client = TestClient(app)

    wav = wrap_pcm16_to_wav(b"\x01\x00" * 160)

    # 1. Invalid audio_out_mode is rejected with 400 Bad Request
    r_bad = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-01", "audio_out_mode": "invalid_hdmi"},
        files={"audio": ("clip.wav", wav, "audio/wav")},
    )
    assert r_bad.status_code == 400
    assert r_bad.json()["error"] == "bad_request"
    assert "Invalid audio_out_mode" in r_bad.json()["message"]

    # 2. Valid discord_voice mode invokes audio_sink_router and tags SSE events
    r_ok = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-01", "audio_out_mode": "discord_voice"},
        files={"audio": ("clip.wav", wav, "audio/wav")},
    )
    assert r_ok.status_code == 200
    assert len(routed_calls) >= 1
    assert routed_calls[0]["mode"] == "discord_voice"
    assert routed_calls[0]["node_id"] == "gotchi-01"
    assert routed_calls[0]["pcm_bytes"] > 0
    assert '"audio_out_mode": "discord_voice"' in r_ok.text


def test_multipart_payload_audio_out_modes():
    wav = wrap_pcm16_to_wav(b"\x00\x00" * 100)

    for mode in ("speaker", "discord_voice", "ble_phone"):
        body, _ = build_multipart_wav(wav, audio_out_mode=mode)
        assert b'name="audio_out_mode"' in body
        assert f"\r\n{mode}\r\n".encode() in body


def test_sse_speaking_ui_sync_when_muted():
    raw_pcm = b"\x10\x00" * 300
    b64_pcm = base64.b64encode(raw_pcm).decode()
    sse_lines = [
        "event: state",
        'data: {"state": "transcribing"}',
        "",
        "event: transcript",
        'data: {"text": "hello", "transcript": "hello"}',
        "",
        "event: reply",
        'data: {"reply": "Routed to AirPods"}',
        "",
        "event: sentence",
        f'data: {{"text": "Routed to AirPods", "engine": "kokoro", "format": "pcm", "sample_rate": 24000, "audio_b64": "{b64_pcm}"}}',
        "",
        "event: done",
        'data: {"duration_ms": 500}',
        "",
    ]

    states_seen: List[str] = []
    pcm_chunks_played: List[bytes] = []
    mute_speaker = True

    def handle_pcm(pcm: bytes, sr: int, final: bool):
        if not mute_speaker:
            pcm_chunks_played.append(pcm)

    ui = parse_sse_stream(
        sse_lines,
        on_state_change=lambda s: states_seen.append(s.state),
        on_audio_pcm=handle_pcm,
    )

    assert "speaking" in states_seen
    assert ui.reply == "Routed to AirPods"
    assert ui.audio_bytes_received == len(raw_pcm)
    assert len(pcm_chunks_played) == 0
