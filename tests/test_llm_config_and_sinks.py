"""
Tests for user-customizable LLM configuration (`backend/llm_config.py`),
`ApiKeyLiveProvider` & `SubscriptionLiveProvider` (`backend/live_gateway.py`),
`DiscordVoiceSink` (`backend/voice_gateway.py`), and C++ `ble_transport.cpp`
fragmentation/reassembly parity.
"""

from pathlib import Path
import subprocess
import tempfile

from fastapi.testclient import TestClient
import pytest

from backend.ble_framing import FrameType, fragment_payload
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


def test_llm_config_modes_and_secret_redaction():
    # 1. Default mock mode requires no credentials
    cfg = LLMConfig()
    cfg.validate()
    pub = cfg.to_public_dict()
    assert pub["auth_mode"] == "mock"
    assert pub["api_key_set"] is False
    assert pub["session_token_set"] is False
    assert "api_key" not in pub
    assert "session_token" not in pub

    # 2. api_key mode rejects empty key, accepts valid key and redacts it in public dict
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
    assert pub_api["provider"] == "gemini"
    assert pub_api["api_key_set"] is True
    assert "test-placeholder-key-not-real" not in str(pub_api)

    # 3. subscription mode rejects missing bridge/session, accepts CLI command or session URL
    with pytest.raises(ValueError, match="requires subscription_command"):
        cfg.update_from_dict({
            "auth_mode": "subscription",
            "provider": "claude_subscription",
            "subscription_command": "",
            "subscription_url": "",
            "session_token": "",
        })

    cfg.update_from_dict({
        "auth_mode": "subscription",
        "provider": "claude_subscription",
        "model": "claude-sonnet-4",
        "subscription_command": "claude -p",
    })
    pub_sub = cfg.to_public_dict()
    assert pub_sub["auth_mode"] == "subscription"
    assert pub_sub["provider"] == "claude_subscription"
    assert pub_sub["subscription_command"] == "claude -p"


def test_runtime_llm_config_endpoints_and_live_provider_switching():
    verifier = BearerTokenVerifier(device_tokens={"unit-1": "tok-secret-1"})
    voice_srv = VoiceGatewayService(verifier=verifier, auth_required=True)
    live_srv = LiveGatewayService(
        verifier=verifier,
        auth_required=True,
        live_mode_enabled=True,
        llm_config=voice_srv.llm_config,
    )
    app = create_app(service=voice_srv, live_service=live_srv)
    client = TestClient(app)

    # Unauthorized request is rejected
    r_unauth = client.get("/api/config/llm")
    assert r_unauth.status_code == 401

    headers = {"Authorization": "Bearer tok-secret-1"}
    r_get = client.get("/api/config/llm", headers=headers)
    assert r_get.status_code == 200
    assert r_get.json()["llm_config"]["auth_mode"] == "mock"
    assert isinstance(create_live_provider(voice_srv.llm_config), MockLiveProvider)

    # Switch to subscription account mode via PUT /api/config/llm
    r_put_sub = client.put(
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
    assert r_put_sub.status_code == 200
    data_sub = r_put_sub.json()["llm_config"]
    assert data_sub["auth_mode"] == "subscription"
    assert data_sub["provider"] == "claude_subscription"
    assert data_sub["discord_voice_bot"] == "mirrormere"
    assert isinstance(create_live_provider(voice_srv.llm_config), SubscriptionLiveProvider)

    # Verify Go Live WebSocket uses SubscriptionLiveProvider dynamically
    with client.websocket_connect("/api/live/ws?token=tok-secret-1") as ws:
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert started["auth_mode"] == "subscription"
        assert started["provider"] == "claude_subscription"

    # Switch to api_key mode via POST /api/config/llm
    r_post_api = client.post(
        "/api/config/llm",
        headers=headers,
        json={
            "auth_mode": "api_key",
            "provider": "gemini",
            "model": "gemini-2.0-flash-live",
            "api_key": "placeholder-gemini-key",
        },
    )
    assert r_post_api.status_code == 200
    assert r_post_api.json()["llm_config"]["api_key_set"] is True
    assert isinstance(create_live_provider(voice_srv.llm_config), ApiKeyLiveProvider)

    with client.websocket_connect("/api/live/ws?token=tok-secret-1") as ws:
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert started["auth_mode"] == "api_key"
        assert started["provider"] == "gemini"


def test_discord_voice_sink_webhook_and_bot_routing():
    posted_payloads = []

    def fake_poster(url, payload):
        posted_payloads.append((url, payload))

    cfg = LLMConfig(
        discord_voice_bot="zero",
        discord_voice_webhook_url="http://203.0.113.10:9099/api/discord/voice",
    )
    sink = DiscordVoiceSink(llm_config=cfg, webhook_poster=fake_poster)
    srv = VoiceGatewayService(llm_config=cfg, discord_sink=sink)
    app = create_app(service=srv)
    client = TestClient(app)

    resp = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-01", "audio_out_mode": "discord_voice", "prompt": "Test sink"},
        files={"audio": ("ptt.wav", b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/wav")},
    )
    assert resp.status_code == 200
    assert len(sink.dispatched_chunks) == 2
    assert len(posted_payloads) == 2
    assert posted_payloads[0][0] == "http://203.0.113.10:9099/api/discord/voice"
    assert posted_payloads[0][1]["bot"] == "zero"
    assert posted_payloads[0][1]["mode"] == "discord_voice"
    assert posted_payloads[0][1]["audio_b64"]


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

    # 1. GATT Service and Characteristic UUIDs match Android GotchiBleRelayService.kt
    for uuid in (
        "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
        "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
        "6E400003-B5A3-F393-E0A9-E50E24DCCA9E",
    ):
        assert uuid in ble_h
        assert uuid in kotlin_srv

    # 2. BLE GATT server advertising, notify descriptor, and T4.1 packet framing
    assert "BLEDevice::init" in ble_cpp
    assert "BLEDevice::setMTU((uint16_t)512)" in ble_cpp
    assert "new BLE2902()" in ble_cpp
    assert "encodePacket(" in ble_cpp
    assert "decodePacket(raw, len, pkt)" in ble_cpp
    assert "s_rx_reassembler.pushPacket(pkt, complete)" in ble_cpp

    # 3. Wired into voice_client.cpp (interactOverBle) and main.cpp (initBleTransport)
    assert '#include "ble_transport.h"' in voice_cpp
    assert "interactOverBle(" in voice_cpp
    assert "gotchi_ble::FrameType::AUDIO_CHUNK" in voice_cpp
    assert "gotchi_ble::FrameType::IMAGE_FRAME" in voice_cpp
    assert "gotchi_ble::FrameType::TURN_COMMIT" in voice_cpp
    assert "gotchi_ble::pollIncomingFrame(" in voice_cpp

    assert '#include "ble_transport.h"' in main_cpp
    assert "gotchi_ble::initBleTransport(cfg.node_id.c_str());" in main_cpp
    assert 'res["ble_connected"] = gotchi_ble::isBlePeerConnected();' in main_cpp

