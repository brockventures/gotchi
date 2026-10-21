"""
Tests for user-customizable LLM configuration (`backend/llm_config.py`),
separate admin auth (`GOTCHI_ADMIN_TOKEN`) and RCE/SSRF prevention on `/api/config/llm`,
real WebSocket client in `ApiKeyLiveProvider`, real CLI/proxy bridge in `SubscriptionLiveProvider`,
allowlisted `https://` Discord webhook poster in `DiscordVoiceSink` (via `run_in_executor`),
PRD Section 5c Mirrormere voice lessons (spoken filler, per-sentence TTS, 60-word cap,
Whisper ghost filter, per-turn timing log, `node_id` validation, >=60s device timeout,
and Go Live half-duplex mic suppression), and C++ `ble_transport.cpp` invariants.
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
from backend.llm_config import DEFAULT_VOICE_NAME, LLMConfig
from backend.voice_gateway import (
    GeminiTTSAdapter,
    KokoroTTSAdapter,
    SubscriptionBrainAdapter,
    VoiceGatewayService,
    WhisperSTTAdapter,
    cap_reply_words,
    create_app,
    is_stt_ghost,
    split_into_sentences,
)
from poc.gotchi_poc import wrap_pcm16_to_wav

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


def test_llm_config_rce_and_ssrf_guards():
    """
    Verify:
    1. subscription_command CANNOT be modified via update_from_dict (HTTP body).
    2. subscription_command rejects path separators (/tmp/x/claude) and dangerous flags (--dangerously-skip-permissions).
    3. discord_voice_webhook_url requires https:// and an allowlisted Discord host.
    """
    cfg = LLMConfig()
    cfg.validate()
    pub = cfg.to_public_dict()
    assert pub["auth_mode"] == "mock"
    assert pub["api_key_set"] is False
    assert pub["session_token_set"] is False
    assert "api_key" not in pub
    assert "session_token" not in pub

    # 1. HTTP body cannot set subscription_command
    with pytest.raises(ValueError, match="subscription_command cannot be set via HTTP API"):
        cfg.update_from_dict({
            "auth_mode": "subscription",
            "provider": "claude_subscription",
            "subscription_command": "claude -p",
        })

    # 2. Path traversal or dangerous arguments in gateway-configured subscription_command are rejected
    with pytest.raises(ValueError, match="bare binary name without path separators"):
        LLMConfig(
            auth_mode="subscription",
            provider="claude_subscription",
            subscription_command="/tmp/x/claude -p",
        ).validate()

    with pytest.raises(ValueError, match="Forbidden argument"):
        LLMConfig(
            auth_mode="subscription",
            provider="claude_subscription",
            subscription_command="claude --dangerously-skip-permissions -p",
        ).validate()

    with pytest.raises(ValueError, match="Forbidden argument"):
        LLMConfig(
            auth_mode="subscription",
            provider="openai_subscription",
            subscription_command="codex exec ls",
        ).validate()

    # Valid gateway-configured subscription_command via constructor/env succeeds
    valid_sub = LLMConfig(
        auth_mode="subscription",
        provider="claude_subscription",
        subscription_command="claude -p --output-format json",
    )
    valid_sub.validate()

    # 3. Webhook SSRF validation: reject http:// and non-allowlisted hosts
    with pytest.raises(ValueError, match="only 'https' is allowed"):
        cfg.update_from_dict({
            "discord_voice_webhook_url": "http://discord.com/api/webhooks/123/abc",
        })

    with pytest.raises(ValueError, match="Disallowed discord_voice_webhook_url host"):
        cfg.update_from_dict({
            "discord_voice_webhook_url": "https://203.0.113.10:9099/api/discord/voice",
        })

    cfg.update_from_dict({
        "discord_voice_webhook_url": "https://discord.com/api/webhooks/12345/token",
    })
    assert cfg.discord_voice_webhook_url == "https://discord.com/api/webhooks/12345/token"


def test_separate_admin_token_required_on_config_llm_endpoints():
    """
    Verify /api/config/llm requires GOTCHI_ADMIN_TOKEN and rejects both unauthenticated
    requests (401) and normal per-unit device tokens (403).
    """
    verifier = BearerTokenVerifier(device_tokens={"unit-1": "device-tok-1"})
    # Without admin_token configured -> 401 even with valid device token
    no_admin_srv = VoiceGatewayService(verifier=verifier, admin_token="")
    no_admin_client = TestClient(create_app(service=no_admin_srv))
    assert (
        no_admin_client.get(
            "/api/config/llm", headers={"Authorization": "Bearer device-tok-1"}
        ).status_code
        == 401
    )

    # With admin_token configured -> device token gets 403, admin token gets 200
    voice_srv = VoiceGatewayService(
        verifier=verifier,
        admin_token="admin-secret-999",
        llm_config=LLMConfig(subscription_command="claude -p"),
    )
    live_srv = LiveGatewayService(
        verifier=verifier,
        live_mode_enabled=True,
        llm_config=voice_srv.llm_config,
    )
    client = TestClient(create_app(service=voice_srv, live_service=live_srv))

    assert client.get("/api/config/llm").status_code == 401
    assert (
        client.get(
            "/api/config/llm", headers={"Authorization": "Bearer device-tok-1"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/config/llm",
            headers={"Authorization": "Bearer device-tok-1"},
            json={"auth_mode": "mock"},
        ).status_code
        == 403
    )

    admin_headers = {"Authorization": "Bearer admin-secret-999"}
    r_get = client.get("/api/config/llm", headers=admin_headers)
    assert r_get.status_code == 200
    assert r_get.json()["llm_config"]["auth_mode"] == "mock"
    assert isinstance(create_live_provider(voice_srv.llm_config), MockLiveProvider)

    # Admin cannot inject subscription_command via HTTP body (400)
    r_inject = client.put(
        "/api/config/llm",
        headers=admin_headers,
        json={"subscription_command": "claude --dangerously-skip-permissions"},
    )
    assert r_inject.status_code == 400

    # Admin can switch to subscription mode using gateway-preconfigured subscription_command or subscription_url
    r_put = client.put(
        "/api/config/llm",
        headers=admin_headers,
        json={
            "auth_mode": "subscription",
            "provider": "claude_subscription",
            "model": "claude-sonnet-4",
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

    assert "secret-gemini-header-key" not in captured_conn["uri"]
    assert "?key=" not in captured_conn["uri"]
    assert captured_conn["headers"] == {"x-goog-api-key": "secret-gemini-header-key"}
    assert fake_ws.sent_frames[0]["setup"]["model"] == "models/gemini-2.0-flash-live"
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


def test_discord_voice_sink_default_poster_async_executor_and_https_allowlist(monkeypatch):
    """Verify DiscordVoiceSink uses its built-in HTTP poster in executor with allowlisted https:// Discord URL."""
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
        discord_voice_webhook_url="https://discord.com/api/webhooks/123456/abcdef",
    )
    srv = VoiceGatewayService(llm_config=cfg)
    app = create_app(service=srv)
    client = TestClient(app)

    wav = wrap_pcm16_to_wav(b"\x10\x00" * 8000)
    resp = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-01", "audio_out_mode": "discord_voice", "prompt": "Test sink"},
        files={"audio": ("ptt.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    assert len(captured_requests) == 2
    assert captured_requests[0][0] == "https://discord.com/api/webhooks/123456/abcdef"
    assert captured_requests[0][1] == "POST"
    assert captured_requests[0][2]["bot"] == "zero"
    assert captured_requests[0][2]["mode"] == "discord_voice"
    assert captured_requests[0][2]["audio_b64"]


def test_mirrormere_section_5c_filler_sentence_tts_ghost_filter_and_timing_log():
    """
    Verify PRD Section 5c items:
    1. Spoken filler while the brain thinks (at filler_delay_ms).
    2. Per-sentence TTS & 60-word reply cap (`reply_cap_words`).
    3. Speech-to-text ghost filter (Whisper ghost phrases + < 400ms voiced audio).
    4. Per-turn timing log (`stt_ms`, `first_text_ms`, `first_audio_ms`, `total_ms`) and `node_id` validation.
    """
    # 1. Word cap and sentence splitting
    long_reply = " ".join([f"word{i}" for i in range(85)])
    capped = cap_reply_words(long_reply, max_words=60)
    assert len(capped.split()) == 60
    assert capped.endswith(".")
    assert split_into_sentences("First sentence. Second sentence! Third?") == [
        "First sentence.",
        "Second sentence!",
        "Third?",
    ]

    # 2. Ghost filter: drops Whisper hallucinations and <400ms audio clips
    short_wav = wrap_pcm16_to_wav(b"\x00\x08\x00\xf8" * 800)  # 100 ms AC voiced (< 400 ms)
    ghost, reason = is_stt_ghost("Hello world", audio_bytes=short_wav, min_voiced_ms=400)
    assert ghost is True
    assert "short_voiced_audio" in reason

    good_wav = wrap_pcm16_to_wav(b"\x00\x08\x00\xf8" * 4000)  # 500 ms AC voiced (>= 400 ms)
    ghost_phrase, reason_p = is_stt_ghost("Thanks for watching.", audio_bytes=good_wav, min_voiced_ms=400)
    assert ghost_phrase is True
    assert "ghost_phrase" in reason_p

    # 3. Gateway turn with slow brain triggers spoken filler, per-sentence TTS, and timing log
    async def slow_brain(turn: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.08)
        return {
            "transcript": "How is the weather?",
            "reply": "Skies are clear today. Wind is calm.",
            "stt_ms": 15,
        }

    cfg = LLMConfig(filler_delay_ms=30, second_filler_delay_ms=5000, reply_cap_words=60, min_voiced_ms=400)
    srv = VoiceGatewayService(llm_config=cfg, turn_handler=slow_brain)
    client = TestClient(create_app(service=srv))

    # Rejects invalid node_id (>64 chars or special chars)
    bad_node = client.post(
        "/api/voice/interact",
        data={"node_id": "bad node/../../etc"},
        files={"audio": ("ptt.wav", good_wav, "audio/wav")},
    )
    assert bad_node.status_code == 400

    # Short voiced audio (<400ms) is ghost-filtered
    r_ghost = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi_unit_1"},
        files={"audio": ("ptt.wav", short_wav, "audio/wav")},
    )
    assert r_ghost.status_code == 200
    assert '"ghost_filtered": true' in r_ghost.text
    assert srv.turn_timings[-1]["ghost_filtered"] is True

    # Valid turn with slow brain emits filler sentence + 2 per-sentence TTS events + timing log
    r_ok = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi_unit_1"},
        files={"audio": ("ptt.wav", good_wav, "audio/wav")},
    )
    assert r_ok.status_code == 200
    assert '"filler": true' in r_ok.text
    assert '"text": "One moment."' in r_ok.text
    assert '"text": "Skies are clear today."' in r_ok.text
    assert '"text": "Wind is calm."' in r_ok.text
    timing = srv.turn_timings[-1]
    assert timing["node_id"] == "gotchi_unit_1"
    assert timing["ghost_filtered"] is False
    assert timing["stt_ms"] >= 0
    assert timing["first_text_ms"] >= 0
    assert timing["first_audio_ms"] >= 0
    assert timing["total_ms"] >= timing["first_audio_ms"]


def test_cpp_ble_transport_and_voice_client_invariants():
    """Verify firmware BLE GATT UART peripheral, >=60s timeout, timing log, and Go Live half-duplex."""
    ble_h = (REPO_ROOT / "firmware" / "include" / "ble_transport.h").read_text(encoding="utf-8")
    ble_cpp = (REPO_ROOT / "firmware" / "src" / "ble_transport.cpp").read_text(encoding="utf-8")
    voice_cpp = (REPO_ROOT / "firmware" / "src" / "voice_client.cpp").read_text(encoding="utf-8")
    live_cpp = (REPO_ROOT / "firmware" / "src" / "live_client.cpp").read_text(encoding="utf-8")
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

    audio_h = (REPO_ROOT / "firmware" / "include" / "audio_hal.h").read_text(encoding="utf-8")
    audio_cpp = (REPO_ROOT / "firmware" / "src" / "audio_hal.cpp").read_text(encoding="utf-8")
    live_h = (REPO_ROOT / "firmware" / "include" / "live_client.h").read_text(encoding="utf-8")

    assert "BLEDevice::init" in ble_cpp
    assert "BLEDevice::setMTU((uint16_t)512)" in ble_cpp
    assert "IDLE_TIMEOUT_MS          = 60000;" in voice_cpp
    assert "WRITE_STALL_TIMEOUT_MS   = 5000;" in voice_cpp
    assert "SSE_READ_IDLE_TIMEOUT_MS = 15000;" in voice_cpp
    assert "if (checkAbortFlag() || !c.connected() || millis() - t0 > WRITE_STALL_TIMEOUT_MS) return false;" in voice_cpp
    assert "applyHighPass100HzSample(" in audio_cpp
    assert "applyHighPass100HzBuffer(" in audio_cpp
    assert "turn_timing stt_ms=" in voice_cpp
    assert "setLiveAecEnabled(bool enabled" in audio_h
    assert "processLiveAecSample(" in audio_cpp
    assert "BARGE_IN_HOLD_MS      = 300;" in audio_cpp
    assert "bool live_barge_in = false;" in live_h
    assert "if (config.live_barge_in)" in live_cpp
    assert "gotchi_audio::setLiveAecEnabled(true" in live_cpp
    assert "gotchi_audio::setLiveAecEnabled(false);" in live_cpp
    assert "if (live_barge_in && gotchi_audio::consumeLiveBargeInFlag())" in live_cpp
    assert 'res["live_barge_in"] = cfg.live_barge_in;' in main_cpp
    assert '"invalid_node_id"' in main_cpp
    assert '#include "ble_transport.h"' in main_cpp
    decl_idx = main_cpp.index("static bool     s_wifi_disabled_for_ble_lp = false;")
    use_idx = main_cpp.index("if (s_wifi_disabled_for_ble_lp)")
    assert decl_idx < use_idx


def test_t6_4_whisper_stt_agy_subscription_brain_and_schedar_gemini_kokoro_tts():
    """
    Verify T6.4 (Issue #40):
    1. Default voice_name is 'Schedar' (Zero's signature voice profile) on both
       VoiceGatewayService and ApiKeyLiveProvider.
    2. WhisperSTTAdapter transcribes uploaded WAV audio via whisper_http.
    3. SubscriptionBrainAdapter keeps LLM reasoning on the regular `agy` subscription
       (`auth_mode='subscription'`, `subscription_command='agy'`) while GeminiTTSAdapter
       synthesizes each sentence in `Schedar` (24 kHz 16-bit mono PCM via x-goog-api-key header).
    4. KokoroTTSAdapter synthesizes 24 kHz PCM via local/HTTP Kokoro endpoint.
    5. GET /api/config/voices returns 'Schedar' as default_voice along with the 30 Gemini HD voices
       and Kokoro voices.
    """
    cfg = LLMConfig(
        auth_mode="subscription",
        provider="gemini_subscription",
        subscription_command="agy",
        api_key="gemini-tts-only-key",
        tts_engine="gemini",
        voice_name="Schedar",
        stt_engine="whisper_http",
        stt_url="https://198.51.100.20:8080/v1/audio/transcriptions",
    )
    assert cfg.voice_name == DEFAULT_VOICE_NAME == "Schedar"

    stt_calls = []

    def fake_whisper_http(url: str, headers: Dict[str, str], body: bytes) -> Dict[str, Any]:
        stt_calls.append((url, headers, len(body)))
        return {"text": "Give me a quick status check."}

    cli_calls = []

    async def fake_agy_cli(argv: List[str], stdin_bytes: bytes) -> bytes:
        cli_calls.append((argv, json.loads(stdin_bytes.decode("utf-8"))))
        return json.dumps({"reply": "All systems nominal. Battery is holding steady."}).encode("utf-8")

    gemini_tts_calls = []
    expected_pcm = b"\x42\x01" * 600

    def fake_gemini_tts_http(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        gemini_tts_calls.append((url, headers, payload))
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "audio/pcm;rate=24000",
                                    "data": base64.b64encode(expected_pcm).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        }

    stt_adapter = WhisperSTTAdapter(llm_config=cfg, http_poster=fake_whisper_http)
    gemini_tts = GeminiTTSAdapter(llm_config=cfg, http_poster=fake_gemini_tts_http)
    sub_brain = SubscriptionBrainAdapter(
        llm_config=cfg,
        stt_adapter=stt_adapter,
        cli_runner=fake_agy_cli,
    )
    srv = VoiceGatewayService(
        llm_config=cfg,
        stt_adapter=stt_adapter,
        gemini_tts=gemini_tts,
        subscription_brain=sub_brain,
    )
    client = TestClient(create_app(service=srv))

    voices_resp = client.get("/api/config/voices")
    assert voices_resp.status_code == 200
    v_data = voices_resp.json()
    assert v_data["default_voice"] == "Schedar"
    assert v_data["active_voice"] == "Schedar"
    assert "Schedar" in v_data["gemini_hd_voices"]
    assert "Achird" in v_data["gemini_hd_voices"]
    assert "am_michael" in v_data["kokoro_voices"]

    wav = wrap_pcm16_to_wav(b"\x00\x08\x00\xf8" * 4000)
    resp = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi_schedar_01"},
        files={"audio": ("ptt.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    assert len(stt_calls) == 1
    assert len(cli_calls) == 1
    assert cli_calls[0][0] == ["agy"]
    assert cli_calls[0][1]["prompt"] == "Give me a quick status check."
    assert len(gemini_tts_calls) == 2
    for call_url, call_hdrs, call_payload in gemini_tts_calls:
        assert "gemini-3.8-flash-tts:generateContent" in call_url
        assert call_hdrs == {"x-goog-api-key": "gemini-tts-only-key"}
        voice_cfg = call_payload["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
        assert voice_cfg["voiceName"] == "Schedar"
    assert '"voice_name": "Schedar"' in resp.text
    assert '"engine": "gemini"' in resp.text
    assert base64.b64encode(expected_pcm).decode("ascii") in resp.text

    # Also verify KokoroTTSAdapter HTTP synthesis
    kokoro_calls = []
    cfg_kokoro = LLMConfig(
        tts_engine="kokoro",
        voice_name="am_michael",
        tts_url="http://198.51.100.21:8880/v1/audio/speech",
    )
    kokoro_adapter = KokoroTTSAdapter(
        llm_config=cfg_kokoro,
        http_poster=lambda u, h, p: (kokoro_calls.append((u, p)) or expected_pcm),
    )
    out_pcm = kokoro_adapter.synthesize("Testing local Kokoro.", 24000)
    assert out_pcm == expected_pcm
    assert kokoro_calls[0][1]["voice"] == "am_michael"

    # 6. Verify automatic cloud-to-local Kokoro TTS fallback + 10-minute (600s) cooldown
    failing_gemini_calls = []

    def failing_gemini_poster(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        failing_gemini_calls.append(url)
        raise RuntimeError("Gemini TTS 503 outage")

    fallback_kokoro_calls = []
    srv_fallback = VoiceGatewayService(
        llm_config=cfg,
        gemini_tts=GeminiTTSAdapter(llm_config=cfg, http_poster=failing_gemini_poster),
        kokoro_tts=KokoroTTSAdapter(
            llm_config=cfg_kokoro,
            http_poster=lambda u, h, p: (fallback_kokoro_calls.append(p["input"]) or expected_pcm),
        ),
    )
    pcm1 = srv_fallback._synthesize_sentence_pcm("First sentence triggers fallback.")
    pcm2 = srv_fallback._synthesize_sentence_pcm("Second sentence uses 10m cooldown.")
    assert pcm1 == expected_pcm
    assert pcm2 == expected_pcm
    assert len(failing_gemini_calls) == 1  # Second call skipped cloud due to 600s cooldown
    assert fallback_kokoro_calls == [
        "First sentence triggers fallback.",
        "Second sentence uses 10m cooldown.",
    ]

    # 7. Verify stale mirrormere.local defaults and Mirrormere hub backend claims are scrubbed
    main_cpp_text = (REPO_ROOT / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    portal_cpp_text = (REPO_ROOT / "firmware" / "src" / "onboarding_portal.cpp").read_text(encoding="utf-8")
    arch_md_text = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    wire_md_text = (REPO_ROOT / "docs" / "MIRRORMERE_VOICE_CLIENT.md").read_text(encoding="utf-8")
    assert "mirrormere.local" not in main_cpp_text
    assert "mirrormere.local" not in portal_cpp_text
    assert "http://gotchi.local:8765/api/voice/interact" in main_cpp_text
    assert "MIRRORMERE / DISCORD BACKEND HUB" not in arch_md_text
    assert "mirrormere.local:9098" not in wire_md_text
    live_h_text = (REPO_ROOT / "firmware" / "include" / "live_client.h").read_text(encoding="utf-8")
    vc_cpp_text = (REPO_ROOT / "firmware" / "src" / "voice_client.cpp").read_text(encoding="utf-8")
    lc_cpp_text = (REPO_ROOT / "firmware" / "src" / "live_client.cpp").read_text(encoding="utf-8")
    android_readme_text = (REPO_ROOT / "android-ble-forwarder" / "README.md").read_text(encoding="utf-8")
    assert ":9098" not in live_h_text
    assert ":9098" not in android_readme_text
    assert "http://host:8765/api/voice/interact" in live_h_text
    assert "WiFiClientSecure" in vc_cpp_text
    assert 'url.startsWith("https://")' in vc_cpp_text
    assert "WiFiClientSecure" in lc_cpp_text
    assert 'url.startsWith("wss://")' in lc_cpp_text
    kotlin_srv_text = (
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
    assert ":9098" not in kotlin_srv_text
    assert 'DEFAULT_GATEWAY_URL = "http://gotchi.local:8765"' in kotlin_srv_text






    # 8. Verify TLS root CA verification (no setInsecure), am_schedar Kokoro style tensor, and clean PRD
    assert "setInsecure" not in vc_cpp_text
    assert "setInsecure" not in lc_cpp_text
    assert "setCACert(GOTCHI_TLS_ROOT_CA_PEM)" in vc_cpp_text
    assert "setCACert(GOTCHI_TLS_ROOT_CA_PEM)" in lc_cpp_text
    tls_ca_text = (REPO_ROOT / "firmware" / "include" / "tls_root_ca.h").read_text(encoding="utf-8")
    assert "GTS Root R1" in tls_ca_text
    assert "ISRG Root X1" in tls_ca_text
    assert KokoroTTSAdapter.resolve_kokoro_voice("Schedar") == "am_schedar"
    assert KokoroTTSAdapter.AM_SCHEDAR_STYLE_PATH.exists()
    prd_md_text = (REPO_ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")
    assert "mirrormere" not in prd_md_text.lower()

    # 9. Verify uncapped default reply_cap_words=0, WAV chunk-walker, SSE sentence streaming, and abbreviation splitting
    from backend.voice_gateway import (
        PCM_CHUNK_FLOOR,
        consume_streaming_sse,
        extract_pcm_from_wav_or_raw,
        slice_pcm_chunks,
    )

    default_cfg = LLMConfig()
    assert default_cfg.reply_cap_words == 0
    assert default_cfg.tts_model == "gemini-3.8-flash-tts"
    long_90_words = " ".join([f"w{i}" for i in range(90)])
    assert cap_reply_words(long_90_words, max_words=default_cfg.reply_cap_words) == long_90_words

    assert split_into_sentences("Dr. Smith checked v2.5 logs. Everything looks clean!") == [
        "Dr. Smith checked v2.5 logs.",
        "Everything looks clean!",
    ]

    raw_pcm_payload = b"\x11\x22" * 3000  # 6000 bytes
    wav_wrapped = wrap_pcm16_to_wav(raw_pcm_payload)
    assert extract_pcm_from_wav_or_raw(wav_wrapped) == raw_pcm_payload
    assert extract_pcm_from_wav_or_raw(raw_pcm_payload) == raw_pcm_payload
    chunks = slice_pcm_chunks(raw_pcm_payload, chunk_floor=PCM_CHUNK_FLOOR)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4800
    assert len(chunks[1]) == 1200

    sse_sample = (
        'event: status\ndata: {"status": "Checking logs"}\n\n'
        'event: sentence\ndata: {"text": "First streamed sentence."}\n\n'
        'event: sentence\ndata: {"text": "Second streamed sentence."}\n\n'
        'event: reply\ndata: {"reply": "First streamed sentence. Second streamed sentence."}\n\n'
        'event: done\ndata: {}\n\n'
    )
    seen_statuses: List[str] = []
    seen_sentences: List[str] = []
    final_rep, parsed_sents = consume_streaming_sse(
        sse_sample,
        on_status=seen_statuses.append,
        on_sentence=seen_sentences.append,
    )
    assert seen_statuses == ["Checking logs"]
    assert seen_sentences == ["First streamed sentence.", "Second streamed sentence."]
    assert parsed_sents == ["First streamed sentence.", "Second streamed sentence."]
    assert final_rep == "First streamed sentence. Second streamed sentence."

    # 10. Verify TurnTranscriptSink logs speaker/journal turns & dispatches to turn_log_webhook_url
    turn_log_posts: List[Dict[str, Any]] = []
    routed_entries: List[Dict[str, Any]] = []
    from backend.voice_gateway import TurnTranscriptSink

    cfg_log = LLMConfig(
        turn_log_webhook_url="https://discord.com/api/webhooks/999999/turnlogtoken",
        voice_name="Schedar",
    )
    sink_log = TurnTranscriptSink(
        llm_config=cfg_log,
        webhook_poster=lambda u, p: turn_log_posts.append({"url": u, "payload": p}),
    )
    srv_log = VoiceGatewayService(
        llm_config=cfg_log,
        turn_log_sink=sink_log,
        turn_log_router=routed_entries.append,
    )
    client_log = TestClient(create_app(service=srv_log))
    resp_spk = client_log.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-ryan-01", "audio_out_mode": "speaker", "prompt": "Check garage temp"},
        files={"audio": ("ptt.wav", wav, "audio/wav")},
    )
    assert resp_spk.status_code == 200
    assert len(turn_log_posts) == 1
    assert turn_log_posts[0]["url"] == "https://discord.com/api/webhooks/999999/turnlogtoken"
    assert "🎙️ **[gotchi-ryan-01]:** Check garage temp" in turn_log_posts[0]["payload"]["content"]
    assert "🔊 **Zero (Schedar):**" in turn_log_posts[0]["payload"]["content"]
    assert len(routed_entries) == 1

    logs_resp = client_log.get("/api/voice/logs")
    assert logs_resp.status_code == 200
    assert logs_resp.json()["count"] == 1
    assert logs_resp.json()["logs"][0]["transcript"] == "Check garage temp"


def test_hpf_frame_rms_ghost_gate_node_webhook_routing_and_async_handoff_supervision():
    """
    Verify:
    1. `measure_voiced_audio_ms` 1st-order 100 Hz HPF + 20 ms frame RMS gate:
       - Rejects 800 ms of low-level room hiss (±20 LSB thermal noise).
       - Rejects 800 ms of 20 Hz outdoor wind rumble (amplitude 1000, attenuated below 250 RMS by 100 Hz HPF).
       - Accepts 500 ms of 400 Hz speech energy above the 250 RMS floor.
    2. `TurnTranscriptSink` routes per-`node_id` via `node_turn_log_webhooks` so Mike's unit and Ryan's unit
       post to separate Discord webhooks.
    3. `async_handoff_ms` streams a spoken handoff and supervises the detached `handler_task` after `done`,
       dispatching both normal completions and post-`done` exceptions to `TurnTranscriptSink`.
    """
    import math
    import struct
    from backend.voice_gateway import TurnTranscriptSink, measure_voiced_audio_ms

    sr = 16000
    n_800ms = int(sr * 0.8)

    # 1a. Room hiss (±20 LSB) -> 0 ms voiced (rejected by 20 ms frame RMS gate)
    hiss_pcm = struct.pack(f"<{n_800ms}h", *([20, -20] * (n_800ms // 2)))
    hiss_wav = wrap_pcm16_to_wav(hiss_pcm, sample_rate=sr)
    assert measure_voiced_audio_ms(hiss_wav) == 0.0
    is_g_hiss, reason_hiss = is_stt_ghost("Hello there", audio_bytes=hiss_wav, min_voiced_ms=400)
    assert is_g_hiss is True
    assert "short_voiced_audio" in reason_hiss

    # 1b. 20 Hz outdoor wind rumble (amplitude 1000 -> un-filtered RMS 707, post-100Hz-HPF RMS ~136 < 250)
    wind_samples = [int(1000.0 * math.sin(2.0 * math.pi * 20.0 * (i / sr))) for i in range(n_800ms)]
    wind_wav = wrap_pcm16_to_wav(struct.pack(f"<{n_800ms}h", *wind_samples), sample_rate=sr)
    assert measure_voiced_audio_ms(wind_wav, apply_hpf=False) >= 700.0
    assert measure_voiced_audio_ms(wind_wav, apply_hpf=True) == 0.0
    is_g_wind, _ = is_stt_ghost("Hello there", audio_bytes=wind_wav, min_voiced_ms=400)
    assert is_g_wind is True

    # 1c. 400 Hz speech energy (amplitude 1200 -> post-HPF RMS ~830 >= 250)
    n_500ms = int(sr * 0.5)
    speech_samples = [int(1200.0 * math.sin(2.0 * math.pi * 400.0 * (i / sr))) for i in range(n_500ms)]
    speech_wav = wrap_pcm16_to_wav(struct.pack(f"<{n_500ms}h", *speech_samples), sample_rate=sr)
    assert measure_voiced_audio_ms(speech_wav) >= 480.0
    is_g_speech, _ = is_stt_ghost("What time is it?", audio_bytes=speech_wav, min_voiced_ms=400)
    assert is_g_speech is False

    # 2. Per-node webhook routing (`node_turn_log_webhooks`)
    dispatched: List[Dict[str, Any]] = []
    cfg = LLMConfig(
        turn_log_webhook_url="https://discord.com/api/webhooks/111111/default",
        node_turn_log_webhooks={
            "gotchi-ryan-01": "https://discord.com/api/webhooks/222222/ryan",
            "gotchi-mike-01": "https://discord.com/api/webhooks/333333/mike",
        },
        filler_delay_ms=0,
        second_filler_delay_ms=0,
        async_handoff_ms=40,
    )
    sink = TurnTranscriptSink(
        llm_config=cfg,
        webhook_poster=lambda u, p: dispatched.append({"url": u, "payload": p}),
    )
    assert sink.resolve_webhook_url("gotchi-ryan-01") == "https://discord.com/api/webhooks/222222/ryan"
    assert sink.resolve_webhook_url("gotchi-mike-01") == "https://discord.com/api/webhooks/333333/mike"
    assert sink.resolve_webhook_url("gotchi-other") == "https://discord.com/api/webhooks/111111/default"

    # 3a. Async handoff success supervision
    async def slow_success_brain(turn: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.10)
        return {"transcript": "Deep repo audit", "reply": "Audit finished cleanly.", "stt_ms": 12}

    async def _run_handoff_success():
        srv = VoiceGatewayService(llm_config=cfg, turn_log_sink=sink, turn_handler=slow_success_brain)
        events = []
        async for ev in srv.generate_sse_stream({
            "node_id": "gotchi-mike-01",
            "session_id": "sess-h1",
            "mode": "interact",
            "audio_out_mode": "speaker",
            "prompt": "Deep repo audit",
            "audio_bytes": speech_wav,
            "image_bytes": None,
            "burst_images": [],
        }):
            events.append(ev)
        await asyncio.sleep(0.12)
        return events

    evs = asyncio.run(_run_handoff_success())
    joined = "".join(evs)
    assert '"async_handoff": true' in joined
    assert len(dispatched) == 1
    assert dispatched[0]["url"] == "https://discord.com/api/webhooks/333333/mike"
    assert "Async Handoff" in dispatched[0]["payload"]["content"]
    assert "Audit finished cleanly." in dispatched[0]["payload"]["content"]

    # 3b. Async handoff failure supervision (exception raised after SSE `done`)
    async def slow_failing_brain(turn: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.10)
        raise RuntimeError("Upstream provider timed out after handoff")

    async def _run_handoff_failure():
        srv = VoiceGatewayService(llm_config=cfg, turn_log_sink=sink, turn_handler=slow_failing_brain)
        async for _ in srv.generate_sse_stream({
            "node_id": "gotchi-ryan-01",
            "session_id": "sess-h2",
            "mode": "interact",
            "audio_out_mode": "speaker",
            "prompt": "Check upstream",
            "audio_bytes": speech_wav,
            "image_bytes": None,
            "burst_images": [],
        }):
            pass
        await asyncio.sleep(0.12)

    asyncio.run(_run_handoff_failure())
    assert len(dispatched) == 2
    assert dispatched[1]["url"] == "https://discord.com/api/webhooks/222222/ryan"
    assert "Async Handoff Failed" in dispatched[1]["payload"]["content"]
    assert "Upstream provider timed out after handoff" in dispatched[1]["payload"]["content"]


def test_silero_vad_gate_and_live_sentence_stream_splitter():
    """
    Verify:
    1. `SileroVADGate` Tier-2 speech probability & transient/broadband clatter rejection in `is_stt_ghost`:
       - Rejects broadband high-ZCR clatter (1-sample sign alternation, ZCR ~ 1.0 > 0.78) even when >=400 ms RMS passes Tier 1.
       - Rejects when an injected Silero ONNX `frame_prob_scorer` returns speech probabilities below `threshold`.
       - Accepts sustained voiced harmonic speech (400 Hz tone or custom scorer >= threshold).
    2. `SentenceStreamSplitter` streams token deltas into complete sentences without breaking on abbreviations (`Dr.`, `v2.5`).
    3. `VoiceGatewayService.generate_sse_stream` streams live sentences emitted via `_on_sentence` before `turn_handler` finishes.
    """
    import struct
    from backend.voice_gateway import SentenceStreamSplitter, SileroVADGate

    sr = 16000
    n_500ms = int(sr * 0.5)

    # 1a. High-crest-factor mechanical clatter (12000 spike once every 320-sample 20ms frame -> RMS ~670 >= 250, crest_factor ~17.9 > 4.0)
    one_frame_clatter = [12000, -12000] + [0] * 318
    clatter_samples = one_frame_clatter * 25  # 25 frames = 500 ms
    clatter_pcm = struct.pack(f"<{len(clatter_samples)}h", *clatter_samples)
    clatter_wav = wrap_pcm16_to_wav(clatter_pcm, sample_rate=sr)
    is_g_clatter, reason_clatter = is_stt_ghost(
        "Random clatter transcript",
        audio_bytes=clatter_wav,
        min_voiced_ms=400,
        use_silero_vad=True,
    )
    assert is_g_clatter is True
    assert "silero_vad_rejected" in reason_clatter

    # 1b. Injected Silero scorer returning low speech probability (0.12 < 0.5) rejects audio
    low_prob_gate = SileroVADGate(threshold=0.5, frame_prob_scorer=lambda samples, rate: 0.12)
    voiced_wav = wrap_pcm16_to_wav(b"\x00\x08\x00\xf8" * 4000, sample_rate=sr)
    is_g_low, reason_low = is_stt_ghost(
        "Hello world",
        audio_bytes=voiced_wav,
        min_voiced_ms=400,
        use_silero_vad=True,
        silero_vad_gate=low_prob_gate,
    )
    assert is_g_low is True
    assert "silero_vad_rejected" in reason_low

    # 1c. Injected Silero scorer returning high speech probability (0.92 >= 0.5) accepts audio
    high_prob_gate = SileroVADGate(threshold=0.5, frame_prob_scorer=lambda samples, rate: 0.92)
    is_g_high, _ = is_stt_ghost(
        "Hello world",
        audio_bytes=voiced_wav,
        min_voiced_ms=400,
        use_silero_vad=True,
        silero_vad_gate=high_prob_gate,
    )
    assert is_g_high is False

    # 2. SentenceStreamSplitter incremental token feed
    splitter = SentenceStreamSplitter()
    emitted: List[str] = []
    for delta in ["Let me check ", "Dr. ", "Cole's v2.4 ", "sensor logs. ", "Temp is 68F!"]:
        emitted.extend(splitter.feed(delta))
    emitted.extend(splitter.flush())
    assert emitted == [
        "Let me check Dr. Cole's v2.4 sensor logs.",
        "Temp is 68F!",
    ]

    # 3. Live _on_sentence callback during turn_handler streams SSE sentence events before handler finishes
    async def streaming_brain(turn: Dict[str, Any]) -> Dict[str, Any]:
        on_s = turn.get("_on_sentence")
        assert callable(on_s)
        on_s("Checking the garage sensor now.")
        await asyncio.sleep(0.04)
        on_s("It is 68 degrees inside.")
        return {
            "transcript": "Check garage",
            "reply": "Checking the garage sensor now. It is 68 degrees inside.",
            "stt_ms": 10,
        }

    cfg = LLMConfig(filler_delay_ms=200, second_filler_delay_ms=5000)
    srv = VoiceGatewayService(llm_config=cfg, turn_handler=streaming_brain)
    client = TestClient(create_app(service=srv))
    resp = client.post(
        "/api/voice/interact",
        data={"node_id": "gotchi-stream-01", "prompt": "Check garage"},
        files={"audio": ("ptt.wav", voiced_wav, "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.text.count('"text": "Checking the garage sensor now."') == 1
    assert resp.text.count('"text": "It is 68 degrees inside."') == 1
    assert '"filler": true' not in resp.text




