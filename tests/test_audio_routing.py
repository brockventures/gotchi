"""
Unit tests for audio reply routing modes (F8 / T3.3).
Tests audio_out_mode validation, multipart encoding, and muted speaker SSE parsing.
"""
import base64
import json
from typing import Dict, Any, List
from poc.gotchi_poc import (
    GotchiUIState,
    build_multipart_wav,
    parse_sse_stream,
    wrap_pcm16_to_wav,
)


def mock_handle_rpc_config(req_json: str, cfg: Dict[str, Any]) -> str:
    """Mock RPC config handler mirroring firmware/src/main.cpp."""
    req = json.loads(req_json)
    cmd = req.get("cmd", "")
    res = {"cmd": cmd, "ok": True}

    if cmd == "get_config":
        res["audio_out_mode"] = cfg.get("audio_out_mode", "speaker")
    elif cmd == "set_config":
        if "audio_out_mode" in req and isinstance(req["audio_out_mode"], str):
            mode = req["audio_out_mode"]
            if mode in ("speaker", "discord_voice", "ble_phone"):
                cfg["audio_out_mode"] = mode
    else:
        res["ok"] = False
        res["error"] = "unknown_command"

    return json.dumps(res)


def test_audio_out_mode_rpc_validation():
    cfg = {"audio_out_mode": "speaker"}

    # Query initial
    res1 = json.loads(mock_handle_rpc_config('{"cmd": "get_config"}', cfg))
    assert res1["audio_out_mode"] == "speaker"

    # Set valid mode discord_voice
    mock_handle_rpc_config('{"cmd": "set_config", "audio_out_mode": "discord_voice"}', cfg)
    assert cfg["audio_out_mode"] == "discord_voice"

    # Set valid mode ble_phone
    mock_handle_rpc_config('{"cmd": "set_config", "audio_out_mode": "ble_phone"}', cfg)
    assert cfg["audio_out_mode"] == "ble_phone"

    # Set invalid mode should be rejected / ignored
    mock_handle_rpc_config('{"cmd": "set_config", "audio_out_mode": "invalid_hdmi"}', cfg)
    assert cfg["audio_out_mode"] == "ble_phone"


def test_multipart_payload_audio_out_modes():
    wav = wrap_pcm16_to_wav(b"\x00\x00" * 100)

    # 1. Default speaker
    body_spk, _ = build_multipart_wav(wav, audio_out_mode="speaker")
    assert b'name="audio_out_mode"' in body_spk
    assert b"\r\nspeaker\r\n" in body_spk

    # 2. Discord voice
    body_disc, _ = build_multipart_wav(wav, audio_out_mode="discord_voice")
    assert b'name="audio_out_mode"' in body_disc
    assert b"\r\ndiscord_voice\r\n" in body_disc

    # 3. BLE phone
    body_ble, _ = build_multipart_wav(wav, audio_out_mode="ble_phone")
    assert b'name="audio_out_mode"' in body_ble
    assert b"\r\nble_phone\r\n" in body_ble


def test_sse_speaking_ui_sync_when_muted():
    """
    Verifies that when audio playback is muted (e.g. discord_voice or ble_phone),
    incoming SSE sentence/audio_chunk events still transition the UI state to
    'speaking', track received audio bytes, and update reply text.
    """
    raw_pcm = b"\x10\x00" * 300  # 600 bytes
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

    # Emulate audio_out_mode = "discord_voice": on_audio_pcm is suppressed or muted,
    # but on_state_change is always triggered for UI animation sync
    audio_out_mode = "discord_voice"
    mute_speaker = (audio_out_mode in ("discord_voice", "ble_phone"))

    def handle_pcm(pcm: bytes, sr: int, final: bool):
        if not mute_speaker:
            pcm_chunks_played.append(pcm)

    ui = parse_sse_stream(
        sse_lines,
        on_state_change=lambda s: states_seen.append(s.state),
        on_audio_pcm=handle_pcm,
    )

    # UI animation states MUST have transitioned through 'speaking'
    assert "speaking" in states_seen
    assert ui.reply == "Routed to AirPods"
    assert ui.audio_bytes_received == len(raw_pcm)

    # Local speaker received 0 PCM chunks because it was muted
    assert len(pcm_chunks_played) == 0
