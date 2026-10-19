"""
Tests for Go Live bidirectional streaming client & gateway relay (F19/F21).
"""
import asyncio
import base64
import json
import pytest
from fastapi.testclient import TestClient

from backend.live_gateway import (
    LiveGatewayService,
    MockLiveProvider,
    create_live_app,
)
from backend.gateway_auth import BearerTokenVerifier


def test_live_gateway_disabled_by_default():
    """Verify Go Live mode is disabled by default per F19/F21."""
    srv = LiveGatewayService(live_mode_enabled=False)
    assert not srv.is_enabled()

    app = create_live_app(srv)
    client = TestClient(app)

    # Health check reflects disabled state
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["live_mode_enabled"] is False

    # Session creation rejected with 403
    r_sess = client.post("/api/live/session", json={"node_id": "test-node"})
    assert r_sess.status_code == 403
    assert r_sess.json()["error"] == "live_mode_disabled"


def test_live_gateway_session_flow_when_enabled():
    """Verify session creation when live_mode is explicitly enabled."""
    srv = LiveGatewayService(live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    r_sess = client.post("/api/live/session", json={"node_id": "gotchi-live-01"})
    assert r_sess.status_code == 200
    data = r_sess.json()
    assert data["ok"] is True
    assert data["node_id"] == "gotchi-live-01"
    assert "live-" in data["session_id"]
    assert data["sample_rate_uplink"] == 16000
    assert data["sample_rate_downlink"] == 24000


def test_live_gateway_token_auth():
    """Verify Bearer token authentication in Go Live session endpoint."""
    verifier = BearerTokenVerifier(device_tokens={"gotchi-live-node": "SecretToken123"})
    srv = LiveGatewayService(verifier=verifier, live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    # 1. Missing token -> 401
    r1 = client.post("/api/live/session", json={"node_id": "gotchi-live-node"})
    assert r1.status_code == 401

    # 2. Valid token -> 200
    r2 = client.post(
        "/api/live/session",
        headers={"Authorization": "Bearer SecretToken123"},
        json={"node_id": "gotchi-live-node"},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


def test_live_gateway_websocket_audio_and_image_injection():
    """Verify WebSocket bidirectional audio streaming and mid-session image injection."""
    srv = LiveGatewayService(live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    with client.websocket_connect("/api/live/ws") as ws:
        # First event is session started confirmation from provider
        init_ev = ws.receive_json()
        assert init_ev["type"] == "session_started"

        # Stream binary PCM audio chunks (16 kHz mono)
        pcm_chunk = b"\x00\x00" * 320  # 640 bytes
        for _ in range(5):
            ws.send_bytes(pcm_chunk)

        # After 5 chunks, mock provider emits audio event
        audio_ev = ws.receive_json()
        assert audio_ev["type"] == "audio"
        assert audio_ev["sample_rate"] == 24000
        raw_pcm = base64.b64decode(audio_ev["audio_b64"])
        assert len(raw_pcm) > 0

        # Inject single image snapshot
        dummy_jpeg = b"\xff\xd8\xff\xe0testjpeg\xff\xd9"
        ws.send_json({
            "type": "image",
            "frame_index": 0,
            "image_b64": base64.b64encode(dummy_jpeg).decode(),
        })

        img_ev = ws.receive_json()
        assert img_ev["type"] == "text"
        assert "Received frame 0" in img_ev["text"]
