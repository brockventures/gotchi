from fastapi.testclient import TestClient

from backend.gateway_auth import BearerTokenVerifier
from backend.voice_gateway import VoiceGatewayService, create_app
from poc.gotchi_poc import parse_sse_stream, wrap_pcm16_to_wav


def test_voice_gateway_health():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_voice_gateway_missing_payload_400():
    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/voice/interact", data={"node_id": "test-device"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"


def test_voice_gateway_empty_file_parts_rejected_400():
    """Verify 0-byte uploaded audio or image parts do not bypass validation via UploadFile truthiness."""
    app = create_app()
    client = TestClient(app)

    # 1. Empty 0-byte audio upload -> 400
    resp_audio = client.post(
        "/api/voice/interact",
        files={"audio": ("ptt.wav", b"", "audio/wav")},
    )
    assert resp_audio.status_code == 400
    assert "empty" in resp_audio.json()["message"].lower()

    # 2. Empty 0-byte image upload -> 400
    resp_img = client.post(
        "/api/voice/interact",
        files={"image": ("snap.jpg", b"", "image/jpeg")},
    )
    assert resp_img.status_code == 400
    assert "empty" in resp_img.json()["message"].lower()


def test_voice_gateway_auth_enforcement():
    verifier = BearerTokenVerifier(device_tokens={"gotchi-ryan": "secret-token-123"})
    service = VoiceGatewayService(verifier=verifier)
    app = create_app(service=service)
    client = TestClient(app)

    wav = wrap_pcm16_to_wav(b"\x00\x00" * 800)
    files = {"audio": ("ptt.wav", wav, "audio/wav")}

    # 1. Missing auth header -> 401
    resp = client.post("/api/voice/interact", files=files)
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"

    # 2. Invalid auth token -> 403
    resp = client.post(
        "/api/voice/interact",
        files=files,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"

    # 3. Valid auth token -> 200 SSE
    resp = client.post(
        "/api/voice/interact",
        files=files,
        headers={"Authorization": "Bearer secret-token-123"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_f17_cold_start_hotspot_turn():
    """
    F17: From a cold start on a phone hotspot, one push-to-talk turn completes
    and the reply plays via live `sentence` (`audio_b64`) SSE events.
    """
    app = create_app()
    client = TestClient(app)

    pcm = b"\x10\x00" * 8000  # 0.5s audio
    wav = wrap_pcm16_to_wav(pcm, sample_rate=16000, channels=1)

    files = {"audio": ("ptt.wav", wav, "audio/wav")}
    data = {
        "node_id": "gotchi-hotspot-01",
        "session_id": "sess-cold-start-99",
        "audio_out_mode": "speaker",
    }

    resp = client.post("/api/voice/interact", files=files, data=data)

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: sentence" in resp.text

    lines = resp.text.splitlines()
    states_seen = []
    pcm_chunks = []
    ui = parse_sse_stream(
        lines,
        on_state_change=lambda s: states_seen.append(s.state),
        on_audio_pcm=lambda pcm_data, sr, final: pcm_chunks.append((pcm_data, sr, final)),
    )

    assert "speaking" in states_seen
    assert ui.state == "idle"
    assert ui.reply != ""
    assert len(pcm_chunks) >= 2
    assert pcm_chunks[0][1] == 24000
    assert ui.audio_bytes_received > 0


def test_f14_single_snapshot_multimodal_turn():
    """
    F14: Single JPEG camera snapshot attached to a turn.
    """
    app = create_app()
    client = TestClient(app)

    dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 64
    wav = wrap_pcm16_to_wav(b"\x05\x00" * 4000)

    files = {
        "audio": ("ptt.wav", wav, "audio/wav"),
        "image": ("snap.jpg", dummy_jpeg, "image/jpeg"),
    }
    data = {
        "node_id": "gotchi-camera-01",
        "prompt": "What is this part?",
    }

    resp = client.post("/api/voice/interact", files=files, data=data)
    assert resp.status_code == 200

    lines = resp.text.splitlines()
    ui = parse_sse_stream(lines)
    assert "Camera snapshot" in ui.reply


def test_f20_five_photo_burst_multimodal_turn():
    """
    F20: Long press on bottom button takes a burst of five photos over 3 seconds
    and sends them together.
    """
    app = create_app()
    client = TestClient(app)

    dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
    files = {
        f"image_{i}": (f"burst_{i}.jpg", dummy_jpeg, "image/jpeg")
        for i in range(5)
    }
    data = {
        "node_id": "gotchi-burst-01",
        "session_id": "sess-burst-5f",
    }

    resp = client.post("/api/voice/interact", files=files, data=data)
    assert resp.status_code == 200

    lines = resp.text.splitlines()
    ui = parse_sse_stream(lines)
    assert "5-frame burst" in ui.reply
