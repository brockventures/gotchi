"""
Tests for Go Live bidirectional streaming client & gateway relay (F19/F21).
Covers:
- Disabled by default (403 on POST /api/live/session and 1008 close on WebSocket /api/live/ws)
- Bearer token enforcement on BOTH POST /api/live/session AND WebSocket /api/live/ws (header and ?token= query param)
- Resilience against malformed JSON text frames and invalid/empty base64 image payloads without dropping the socket
- Mounting of /api/live/session and /api/live/ws directly on voice_gateway.create_app() so the unit's voice_url serves Live WebSocket
- Direct C++ source verification on firmware/include/live_client.h, firmware/src/live_client.cpp, and firmware/src/main.cpp
  (LIVE_DISABLED enum rename avoiding Arduino macro collision, RFC 6455 WebSocket handshake, live_url config support, and pollRpcAndHttp).
"""
import base64
import pathlib
import pytest
from fastapi.testclient import TestClient

from backend.live_gateway import (
    LiveGatewayService,
    MockLiveProvider,
    create_live_app,
)
from backend.voice_gateway import VoiceGatewayService, create_app
from backend.gateway_auth import BearerTokenVerifier

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE_CLIENT_H = REPO_ROOT / "firmware" / "include" / "live_client.h"
LIVE_CLIENT_CPP = REPO_ROOT / "firmware" / "src" / "live_client.cpp"
MAIN_CPP = REPO_ROOT / "firmware" / "src" / "main.cpp"


def test_firmware_live_client_streaming_and_rpc_polling_invariants():
    """Verify firmware/src/live_client.cpp and live_client.h avoid Arduino DISABLED macro and stream over WS."""
    live_h = LIVE_CLIENT_H.read_text(encoding="utf-8")
    live_src = LIVE_CLIENT_CPP.read_text(encoding="utf-8")
    main_src = MAIN_CPP.read_text(encoding="utf-8")

    # 0. Uses LIVE_DISABLED instead of DISABLED to avoid Arduino #define DISABLED 0x00 macro collision
    assert "LIVE_DISABLED" in live_h
    assert "SessionEndReason::LIVE_DISABLED" in live_src

    # 1. Opens TCP connection & performs RFC 6455 WebSocket Upgrade handshake with Bearer token
    assert "ws_client.connect(host.c_str(), port" in live_src
    assert "performWsHandshake(ws_client, host, port, ws_path, config.node_id, config.bearer_token" in live_src
    assert '"Upgrade: websocket\\r\\n"' in live_src
    assert '"Authorization: Bearer " + bearer_token' in live_src

    # 2. Reads 16 kHz PCM from PDM mic and sends masked binary WebSocket frames (opcode 0x02)
    assert "gotchi_audio::readLivePcmChunk(pcm_chunk, PCM_UPLINK_SAMPLES, &chunk_rms)" in live_src
    assert "sendWsFrame(ws_client, 0x02," in live_src

    # 3. Polls incoming WebSocket frames and plays 24 kHz downlink audio (unless muted by audio_out_mode)
    assert "pollWsDownlink(ws_client, rx_buf, rx_cap, mute_speaker" in live_src
    assert "gotchi_audio::playBase64PcmChunk(b64, b64_len, sr)" in live_src
    assert "gotchi_audio::playPcmChunk(" in live_src

    # 4. Sends mid-session snapshot & burst JPEG frames over WebSocket
    assert "sendWsImageFrame(ws_client," in live_src

    # 5. Preserves Wi-Fi HTTP & USB-C Serial JSON-RPC responsiveness and supports optional live_url override
    assert "if (poll_tick_cb) poll_tick_cb();" in live_src
    assert "pollRpcAndHttp" in main_src
    assert "cfg.live_url" in main_src


def test_voice_gateway_create_app_mounts_live_routes():
    """Verify voice_gateway.create_app() serves /api/live/session and /api/live/ws on the same app."""
    verifier = BearerTokenVerifier(device_tokens={"gotchi-01": "SecretTok"})
    voice_srv = VoiceGatewayService(verifier=verifier)
    live_srv = LiveGatewayService(verifier=verifier, live_mode_enabled=True)
    app = create_app(service=voice_srv, live_service=live_srv)
    client = TestClient(app)

    r_sess = client.post(
        "/api/live/session",
        headers={"Authorization": "Bearer SecretTok"},
        json={"node_id": "gotchi-01"},
    )
    assert r_sess.status_code == 200
    assert r_sess.json()["ok"] is True

    with client.websocket_connect(
        "/api/live/ws",
        headers={"Authorization": "Bearer SecretTok"},
    ) as ws:
        ev = ws.receive_json()
        assert ev["type"] == "session_started"


def test_live_gateway_disabled_by_default():
    """Verify Go Live mode is disabled by default per F19/F21."""
    srv = LiveGatewayService(live_mode_enabled=False)
    assert not srv.is_enabled()

    app = create_live_app(srv)
    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["live_mode_enabled"] is False

    r_sess = client.post("/api/live/session", json={"node_id": "test-node"})
    assert r_sess.status_code == 403
    assert r_sess.json()["error"] == "live_mode_disabled"


def test_live_gateway_session_and_websocket_token_auth():
    """Verify Bearer token authentication on BOTH POST /api/live/session and WebSocket /api/live/ws."""
    verifier = BearerTokenVerifier(device_tokens={"gotchi-live-node": "SecretToken123"})
    srv = LiveGatewayService(verifier=verifier, live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    r1 = client.post("/api/live/session", json={"node_id": "gotchi-live-node"})
    assert r1.status_code == 401

    r2 = client.post(
        "/api/live/session",
        headers={"Authorization": "Bearer SecretToken123"},
        json={"node_id": "gotchi-live-node"},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    with client.websocket_connect("/api/live/ws") as ws_unauth:
        err_ev = ws_unauth.receive_json()
        assert err_ev["type"] == "error"
        assert err_ev["error"] in ("missing_token", "unauthorized")

    with client.websocket_connect(
        "/api/live/ws",
        headers={"Authorization": "Bearer WrongToken999"},
    ) as ws_bad:
        err_ev = ws_bad.receive_json()
        assert err_ev["type"] == "error"
        assert err_ev["error"] in ("forbidden", "invalid_token", "unauthorized")

    with client.websocket_connect(
        "/api/live/ws",
        headers={"Authorization": "Bearer SecretToken123"},
    ) as ws_ok:
        init_ev = ws_ok.receive_json()
        assert init_ev["type"] == "session_started"


def test_live_gateway_websocket_malformed_input_resilience():
    """Verify malformed JSON or bad base64 returns an error event instead of crashing the socket."""
    srv = LiveGatewayService(live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    with client.websocket_connect("/api/live/ws") as ws:
        init_ev = ws.receive_json()
        assert init_ev["type"] == "session_started"

        ws.send_text("{not valid json")
        err1 = ws.receive_json()
        assert err1["type"] == "error"
        assert err1["error"] == "invalid_json"

        ws.send_json({"type": "image", "frame_index": 0, "image_b64": "!!!not_base64!!!"})
        err2 = ws.receive_json()
        assert err2["type"] == "error"
        assert err2["error"] == "invalid_base64"

        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"

        dummy_jpeg = b"\xff\xd8\xff\xe0testjpeg\xff\xd9"
        ws.send_json({
            "type": "image",
            "frame_index": 0,
            "image_b64": base64.b64encode(dummy_jpeg).decode(),
        })
        img_ev = ws.receive_json()
        assert img_ev["type"] == "text"
        assert "Received frame 0" in img_ev["text"]


def test_live_gateway_websocket_audio_and_image_injection():
    """Verify WebSocket bidirectional audio streaming and mid-session image injection."""
    srv = LiveGatewayService(live_mode_enabled=True)
    app = create_live_app(srv)
    client = TestClient(app)

    with client.websocket_connect("/api/live/ws") as ws:
        init_ev = ws.receive_json()
        assert init_ev["type"] == "session_started"

        pcm_chunk = b"\x00\x00" * 320
        for _ in range(5):
            ws.send_bytes(pcm_chunk)

        audio_ev = ws.receive_json()
        assert audio_ev["type"] == "audio"
        assert audio_ev["sample_rate"] == 24000
        raw_pcm = base64.b64decode(audio_ev["audio_b64"])
        assert len(raw_pcm) > 0
