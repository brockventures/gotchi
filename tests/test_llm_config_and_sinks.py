"""
Tests for user-customizable LLM configuration (`backend/llm_config.py`),
real WebSocket client in `ApiKeyLiveProvider`, real CLI/proxy bridge in `SubscriptionLiveProvider`,
default HTTP webhook poster in `DiscordVoiceSink`, unconditional auth on `/api/config/llm`,
and C++ `ble_transport.cpp` peripheral invariants.
"""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List
import urllib.request

from fastapi.testclient import TestClient
import pytest

from backend.gateway_auth import BearerTokenVerifier
from backend.live_gateway import (
    ApiKeyLiveProvider,
    LiveGatewayService,
    MockLiveProvider,
    SubscriptionLiveProvider,
    create_live_provider,
)
from backend.llm_config import LLMConfig
from backend.voice_gateway import DiscordVoiceSink, VoiceGatewayService, create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeAsyncWebSocket:
    """In-memory async WebSocket double capturing sent frames and yielding canned server frames."""

    def __init__(self, incoming_messages: List[Any]):
        self.sent_frames: List[Dict[str, Any]] = []
        self._incoming = list(incoming_messages)
        self.closed = False

    async def send(self, data: str):
        self.sent_frames.append(json.loads(data))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            await asyncio.sleep(0.02)
            raise StopAsyncIteration
        return self._incoming.pop(0)

    async def close(self):
        self.closed = True


def test_llm_config_modes_secret_redaction_and_cli_allowlist():
    cfg = LLMConfig()
    cfg.validate()
    pub = cfg.to_public_dict()
    assert pub["auth_mode"] == "mock"
    assert pub["api_key_set"] is False
    assert pub["session_token_set"] is False
    assert "api_key" not in pub
    assert "session_token" not in pub

    with pytest.raises(ValueError, match="requires a non-empty api_key"):
        cfg.update_from_dict({"auth_mode": "api_key", "provider": "gemini", "api_key": ""})

    cfg.update_from_dict({
        "auth_mode": "api_key",
        "provider": "gemini",
        "model": "gemini-2.0-flash-live",
        "api_key": "test-placeholder-key-not-real",
    })
    pub_api = cfg.to_public_dict()
    assert pub_api["auth_mode"] == "api_key"
    assert pub_api["api_key_set"] is True
    assert "test-placeholder-key-not-real" not in str(pub_api)

    # Rejects arbitrary shell binaries in subscription_command
    with pytest.raises(ValueError, match="Unsupported subscription_command binary"):
        cfg.update_from_dict({
            "auth_mode": "subscription",
            "provider": "claude_subscription",
            "subscription_command": "sh -c 'echo pwned'",
        })

    cfg.update_from_dict({
        "auth_mode": "subscription",
        "provider": "claude_subscription",
        "model": "claude-sonnet-4",
        "subscription_command": "claude -p",
    })
    assert cfg.to_public_dict()["subscription_command"] == "claude -p"


def test_unconditional_auth_on_config_llm_endpoints():
    """Verify /api/config/llm rejects unauthenticated requests even when auth_required=False and no tokens exist."""
    open_srv = VoiceGatewayService(verifier=BearerTokenVerifier(device_tokens={}), auth_required=False)
    open_app = create_app(service=open_srv)
    open_client = TestClient(open_app)

    assert open_client.get("/api/config/llm").status_code == 401
    assert open_client.put("/api/config/llm", json={"auth_mode": "mock"}).status_code == 401
    assert open_client.post("/api/config/llm", json={"auth_mode": "mock"}).status_code == 401

    # With device token configured, valid token succeeds and invalid fails
    verifier = BearerTokenVerifier(device_tokens={"unit-1": "tok-secret-1"})
    voice_srv = VoiceGatewayService(verifier=verifier, auth_required=False)
    live_srv = LiveGatewayService(
        verifier=verifier,
        auth_required=False,
        live_mode_enabled=True,
        llm_config=voice_srv.llm_config,
    )
    app = create_app(service=voice_srv, live_service=live_srv)
    client = TestClient(app)

    assert client.get("/api/config/llm").status_code == 401
    headers = {"Authorization": "Bearer tok-secret-1"}
    r_get = client.get("/api/config/llm", headers=headers)
    assert r_get.status_code == 200
    assert r_get.json()["llm_config"]["auth_mode"] == "mock"
    assert isinstance(create_live_provider(voice_srv.llm_config), MockLiveProvider)

    r_put = client.put(
        "/api/config/llm",
        headers=headers,
        json={
            "auth_mode": "subscription",
            "provider": "claude_subscription",
            "model": "claude-sonnet-4",
            "subscription_command": "claude --print",
            "discord_voice_bot": "mirrormere",
        },
    )
    assert r_put.status_code == 200
    assert isinstance(create_live_provider(voice_srv.llm_config), SubscriptionLiveProvider)


def test_api_key_live_provider_gemini_ws_protocol_and_header_auth():
    """Verify ApiKeyLiveProvider uses header auth (never URL query key) and speaks Gemini BidiGenerateContent."""
    captured_conn: Dict[str, Any] = {}
    pcm_out = b"\x20\x00" * 240
    b64_out = base64.b64encode(pcm_out).decode("ascii")
    gemini_server_msg = json.dumps({
        "serverContent": {
            "modelTurn": {
                "parts": [
                    {"text": "Hello from Gemini Live"},
                    {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": b64_out}},
                ]
            }
        }
    })
    fake_ws = FakeAsyncWebSocket([gemini_server_msg])

    async def fake_connector(uri: str, headers: Dict[str, str]):
        captured_conn["uri"] = uri
        captured_conn["headers"] = headers
        return fake_ws

    cfg = LLMConfig(
        auth_mode="api_key",
        provider="gemini",
        model="gemini-2.0-flash-live",
        api_key="secret-gemini-header-key",
    )
    provider = ApiKeyLiveProvider(config=cfg, ws_connector=fake_connector)

    async def _run():
        await provider.connect("sess-1", "node-1")
        await provider.send_audio_chunk(b"\x01\x02" * 160)
        await provider.send_image_frame(b"\xff\xd8\xff\xe0jpeg", frame_index=2)

        received = []
        async for ev in provider.receive_events():
            received.append(ev)
            if len(received) >= 3:
                break
        await provider.close()
        return received

    events = asyncio.run(_run())

    # Key must be in x-goog-api-key header, NEVER in URL query string
    assert "secret-gemini-header-key" not in captured_conn["uri"]
    assert "?key=" not in captured_conn["uri"]
    assert captured_conn["headers"] == {"x-goog-api-key": "secret-gemini-header-key"}

    # Frame 0: Gemini setup frame; Frame 1: realtimeInput audio; Frame 2: realtimeInput image
    assert fake_ws.sent_frames[0]["setup"]["model"] == "models/gemini-2.0-flash-live"
    assert (
        fake_ws.sent_frames[1]["realtimeInput"]["mediaChunks"][0]["mimeType"]
        == "audio/pcm;rate=16000"
    )
    assert (
        fake_ws.sent_frames[2]["realtimeInput"]["mediaChunks"][0]["mimeType"]
        == "image/jpeg"
    )

    assert events[0]["type"] == "session_started"
    assert events[1] == {"type": "text", "text": "Hello from Gemini Live"}
    assert events[2] == {"type": "audio", "sample_rate": 24000, "audio_b64": b64_out}


def test_subscription_live_provider_cli_and_ws_proxy():
    """Verify SubscriptionLiveProvider invokes real CLI runner and WS proxy with Bearer session token."""
    cli_calls = []

    async def fake_cli_runner(argv: List[str], stdin_payload: bytes) -> bytes:
        cli_calls.append((argv, json.loads(stdin_payload.decode("utf-8"))))
        return json.dumps({"type": "text", "text": "Claude subscription reply"}).encode("utf-8")

    cfg_cli = LLMConfig(
        auth_mode="subscription",
        provider="claude_subscription",
        model="claude-sonnet-4",
        subscription_command="claude -p --output-format json",
    )
    sub_cli = SubscriptionLiveProvider(config=cfg_cli, cli_runner=fake_cli_runner)

    async def _run_cli():
        await sub_cli.connect("sub-sess-1", "node-1")
        await sub_cli.send_audio_chunk(b"\x00\x01" * 80)
        out = []
        async for ev in sub_cli.receive_events():
            out.append(ev)
            if len(out) >= 2:
                break
        await sub_cli.close()
        return out

    cli_events = asyncio.run(_run_cli())
    assert cli_calls[0][0] == ["claude", "-p", "--output-format", "json"]
    assert cli_calls[0][1]["type"] == "audio"
    assert cli_events[1] == {"type": "text", "text": "Claude subscription reply"}

    # WebSocket subscription proxy test
    ws_conn_info: Dict[str, Any] = {}
    fake_sub_ws = FakeAsyncWebSocket([json.dumps({"type": "text", "text": "Proxy WS reply"})])

    async def fake_ws_conn(uri: str, headers: Dict[str, str]):
        ws_conn_info["uri"] = uri
        ws_conn_info["headers"] = headers
        return fake_sub_ws

    cfg_ws = LLMConfig(
        auth_mode="subscription",
        provider="claude_subscription",
        subscription_url="wss://sub-proxy.example.invalid/live",
        session_token="sub-oauth-token-123",
    )
    sub_ws = SubscriptionLiveProvider(config=cfg_ws, ws_connector=fake_ws_conn)

    async def _run_ws():
        await sub_ws.connect("sub-sess-2", "node-2")
        await sub_ws.send_image_frame(b"\xff\xd8\xff\xd9", frame_index=0)
        out = []
        async for ev in sub_ws.receive_events():
            out.append(ev)
            if len(out) >= 2:
                break
        await sub_ws.close()
        return out

    ws_events = asyncio.run(_run_ws())
    assert ws_conn_info["uri"] == "wss://sub-proxy.example.invalid/live"
    assert ws_conn_info["headers"] == {"Authorization": "Bearer sub-oauth-token-123"}
    assert fake_sub_ws.sent_frames[0]["type"] == "image"
    assert ws_events[1] == {"type": "text", "text": "Proxy WS reply"}


def test_discord_voice_sink_default_poster_invoked(monkeypatch):
    """Verify DiscordVoiceSink uses its built-in HTTP poster by default when create_app() runs."""
    captured_requests = []

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(req, timeout=5.0):
        captured_requests.append((
            req.full_url,
            req.get_method(),
            json.loads(req.data.decode("utf-8")),
            timeout,
        ))
        return DummyResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    cfg = LLMConfig(
        discord_voice_bot="zero",
        discord_voice_webhook_url="http://203.0.113.10:9099/api/discord/voice",
    )
    # Pass no custom webhook_poster so default _default_webhook_poster is exercised
    srv = VoiceGatewayService(llm_config=cfg)
    app = create_app(service=srv)
    client = TestClient(app)

    resp = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-01", "audio_out_mode": "discord_voice", "prompt": "Test sink"},
        files={"audio": ("ptt.wav", b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/wav")},
    )
    assert resp.status_code == 200
    assert len(captured_requests) == 2
    assert captured_requests[0][0] == "http://203.0.113.10:9099/api/discord/voice"
    assert captured_requests[0][1] == "POST"
    assert captured_requests[0][2]["bot"] == "zero"
    assert captured_requests[0][2]["mode"] == "discord_voice"
    assert captured_requests[0][2]["audio_b64"]


def test_cpp_ble_transport_and_voice_client_invariants():
    """Verify firmware BLE GATT UART peripheral and voice_client BLE fallback invariants."""
    ble_h = (REPO_ROOT / "firmware" / "include" / "ble_transport.h").read_text(encoding="utf-8")
    ble_cpp = (REPO_ROOT / "firmware" / "src" / "ble_transport.cpp").read_text(encoding="utf-8")
    voice_cpp = (REPO_ROOT / "firmware" / "src" / "voice_client.cpp").read_text(encoding="utf-8")
    main_cpp = (REPO_ROOT / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    kotlin_srv = (
        REPO_ROOT
        / "android-ble-forwarder"
        / "app"
        / "src"
        / "main"
        / "java"
        / "ventures"
        / "brock"
        / "gotchi"
        / "forwarder"
        / "GotchiBleRelayService.kt"
    ).read_text(encoding="utf-8")

    for uuid in (
        "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
        "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
        "6E400003-B5A3-F393-E0A9-E50E24DCCA9E",
    ):
        assert uuid in ble_h
        assert uuid in kotlin_srv

    assert "BLEDevice::init" in ble_cpp
    assert "BLEDevice::setMTU((uint16_t)512)" in ble_cpp
    assert "new BLE2902()" in ble_cpp
    assert "encodePacket(" in ble_cpp
    assert "decodePacket(raw, len, pkt)" in ble_cpp
    assert "s_rx_reassembler.pushPacket(pkt, complete)" in ble_cpp

    assert '#include "ble_transport.h"' in voice_cpp
    assert "interactOverBle(" in voice_cpp
    assert "gotchi_ble::FrameType::AUDIO_CHUNK" in voice_cpp
    assert "gotchi_ble::FrameType::IMAGE_FRAME" in voice_cpp
    assert "gotchi_ble::FrameType::TURN_COMMIT" in voice_cpp
    assert "gotchi_ble::pollIncomingFrame(" in voice_cpp

    assert '#include "ble_transport.h"' in main_cpp
    assert "gotchi_ble::initBleTransport(cfg.node_id.c_str());" in main_cpp
    assert 'res["ble_connected"] = gotchi_ble::isBlePeerConnected();' in main_cpp
