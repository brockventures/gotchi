#!/usr/bin/env python3
"""
GOTCHI V1 — Reference Voice Gateway Server (`POST /api/voice/interact`)
======================================================================
Satisfies:
- F15: Hub wire contract handling per-unit `voice_url` targeting reference gateway.
- F17: Cold-start hotspot turn completion test harness.
- F14 & F20: Multimodal single JPEG snapshot (`image`) and 5-frame burst (`image_0`..`image_4`).
- T3.2: Per-device `BearerTokenVerifier` auth integration.
- T3.3: Discord Voice (`DiscordVoiceSink`) with `https://` allowlisted webhook POST executed in
  `loop.run_in_executor` (never blocking the asyncio event loop) and `ble_phone` audio routing modes.
- T3.4: User-customizable LLM configuration (`GET/PUT/POST /api/config/llm`) requiring a separate
  `admin_token` (`GOTCHI_ADMIN_TOKEN`) unconditionally (device tokens are rejected).
- PRD Section 5c (Mirrormere Voice Lessons):
  1. Spoken filler sentences at `filler_delay_ms` (1200 ms) and `second_filler_delay_ms` (5000 ms)
     while waiting on slow brain/LLM inference.
  2. Per-sentence TTS synthesis (`split_into_sentences`) so the first sentence streams immediately,
     plus `reply_cap_words` (default 60 words) truncation.
  3. Speech-to-text ghost filter dropping Whisper hallucination lines and clips with `< 400 ms`
     of voiced audio.
  4. Per-turn timing log (`stt_ms`, `first_text_ms`, `first_audio_ms`, `total_ms`) and strict
     `node_id` validation (`^[A-Za-z0-9_-]{1,64}$`).
"""

import asyncio
import base64
import hmac
import inspect
import io
import json
import logging
import os
import re
import shlex
import struct
import time
import urllib.request
from typing import Any, AsyncGenerator, Callable, Dict, List, Mapping, Optional, Tuple

try:
    from fastapi import FastAPI, Header, Request
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:
    FastAPI = None

from backend.gateway_auth import BearerTokenVerifier
from backend.llm_config import (
    DEFAULT_VOICE_NAME,
    GEMINI_HD_VOICES,
    KOKORO_VOICES,
    LLMConfig,
    validate_discord_webhook_url,
    validate_subscription_command,
)

logger = logging.getLogger("gotchi_gateway")

NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

WHISPER_GHOST_PHRASES = frozenset({
    "",
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "thanks for listening",
    "subtitles by",
    "subtitles by amara.org",
    "amara.org",
    "you",
    "bye",
    "mbc",
})


def validate_node_id(node_id: str) -> str:
    """Enforces PRD 5c node_id invariant: letters, digits, dash, underscore, max 64 chars."""
    cleaned = str(node_id).strip()
    if not NODE_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid node_id '{cleaned}'; must match ^[A-Za-z0-9_-]{{1,64}}$"
        )
    return cleaned


def normalize_transcript_for_ghost_check(text: str) -> str:
    cleaned = re.sub(r"[^\w\s.]", "", (text or "").lower()).strip()
    cleaned = re.sub(r"\.+$", "", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned)


def measure_voiced_audio_ms(
    wav_bytes: bytes,
    default_sample_rate: int = 16000,
    sample_threshold: int = 1,
) -> float:
    """
    Measures voiced audio duration in milliseconds from a 16-bit mono PCM WAV buffer.
    Parses the RIFF/WAVE header if present (44+ bytes); otherwise treats raw bytes as 16 kHz PCM16.
    """
    if not wav_bytes:
        return 0.0

    sample_rate = default_sample_rate
    pcm_payload = wav_bytes
    if len(wav_bytes) >= 44 and wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE":
        try:
            parsed_sr = struct.unpack_from("<I", wav_bytes, 24)[0]
            if 4000 <= parsed_sr <= 96000:
                sample_rate = parsed_sr
        except struct.error:
            pass
        pcm_payload = wav_bytes[44:]

    num_samples = len(pcm_payload) // 2
    if num_samples <= 0:
        return 0.0

    # Unpack 16-bit signed little-endian samples and count voiced samples
    voiced_samples = 0
    unpack_len = num_samples * 2
    for (sample,) in struct.iter_unpack("<h", pcm_payload[:unpack_len]):
        if abs(sample) >= sample_threshold:
            voiced_samples += 1

    return (voiced_samples / float(sample_rate)) * 1000.0


def is_stt_ghost(
    transcript_text: str,
    audio_bytes: Optional[bytes] = None,
    min_voiced_ms: int = 400,
    has_explicit_prompt: bool = False,
    has_images: bool = False,
) -> Tuple[bool, str]:
    """
    Returns (is_ghost, reason) per PRD Section 5c:
    1. Drops known Whisper silence hallucinations (`WHISPER_GHOST_PHRASES`).
    2. Drops audio-only turns where voiced audio duration is under `min_voiced_ms` (400 ms default).
    """
    norm = normalize_transcript_for_ghost_check(transcript_text)
    if norm in WHISPER_GHOST_PHRASES or norm.startswith("subtitles by "):
        return True, f"ghost_phrase:{norm or 'empty'}"

    if (
        audio_bytes is not None
        and min_voiced_ms > 0
        and not has_explicit_prompt
        and not has_images
    ):
        voiced_ms = measure_voiced_audio_ms(audio_bytes)
        if voiced_ms < float(min_voiced_ms):
            return True, f"short_voiced_audio:{voiced_ms:.1f}ms<{min_voiced_ms}ms"

    return False, ""


def cap_reply_words(text: str, max_words: int = 60) -> str:
    """Caps spoken reply length to `max_words` (PRD 5c default: 60 words)."""
    if max_words <= 0:
        return text.strip()
    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()
    capped = " ".join(words[:max_words])
    if not capped.endswith((".", "!", "?")):
        capped = capped.rstrip(",;:-") + "."
    return capped


def split_into_sentences(text: str) -> List[str]:
    """Splits a reply into individual sentences so TTS starts streaming on sentence 1."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    return parts if parts else [cleaned]


def generate_synthetic_pcm(duration_s: float = 0.25, sample_rate: int = 24000) -> bytes:
    """Generate 16-bit mono PCM audio for reference TTS playback."""
    num_samples = max(1, int(duration_s * sample_rate))
    return b"\x00\x00" * num_samples


class WhisperSTTAdapter:
    """
    Real Speech-to-Text adapter for T6.4 (`Issue #40`) supporting:
    1. `whisper_http`: OpenAI-compatible `/v1/audio/transcriptions` or JSON Whisper endpoint
       (e.g. local `faster-whisper-server`, `whisper.cpp`, or remote Whisper API).
    2. `faster_whisper`: Local in-process `faster_whisper.WhisperModel` when installed.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        http_poster: Optional[Callable[[str, Dict[str, str], bytes], Dict[str, Any]]] = None,
        local_transcriber: Optional[Callable[[bytes, str], str]] = None,
    ):
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.http_poster = http_poster or self._default_http_poster
        self.local_transcriber = local_transcriber
        self._fw_model: Any = None

    @staticmethod
    def _default_http_poster(url: str, headers: Dict[str, str], body: bytes) -> Dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {"text": ""}

    def transcribe(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            return ""
        engine = self.llm_config.stt_engine
        if self.local_transcriber is not None:
            return str(self.local_transcriber(wav_bytes, self.llm_config.stt_model)).strip()

        if engine == "whisper_http" and self.llm_config.stt_url.strip():
            boundary = "----GotchiWhisperBoundary7MA4YWxkTrZu0gW"
            model_name = self.llm_config.stt_model or "whisper-1"
            parts = [
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="model"\r\n\r\n{model_name}\r\n'.encode("utf-8"),
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="ptt.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n".encode("utf-8")
                + wav_bytes
                + f"\r\n--{boundary}--\r\n".encode("utf-8"),
            ]
            body = b"".join(parts)
            headers: Dict[str, str] = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }
            if self.llm_config.api_key.strip():
                headers["Authorization"] = f"Bearer {self.llm_config.api_key.strip()}"
            res = self.http_poster(self.llm_config.stt_url.strip(), headers, body)
            return str(res.get("text") or res.get("transcript") or "").strip()

        if engine == "faster_whisper":
            from faster_whisper import WhisperModel  # type: ignore

            if self._fw_model is None:
                model_id = self.llm_config.stt_model or "base.en"
                self._fw_model = WhisperModel(model_id, device="cpu", compute_type="int8")
            segments, _ = self._fw_model.transcribe(io.BytesIO(wav_bytes), beam_size=1)
            return " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()

        return "What is the status?"


class GeminiTTSAdapter:
    """
    Per-sentence Gemini API TTS adapter (`tts_engine == "gemini"`, default voice `"Schedar"`).
    Allows GOTCHI to run LLM reasoning on the flat-rate `agy` subscription while synthesizing
    each short sentence in Zero's signature `"Schedar"` voice (24 kHz 16-bit mono PCM).
    Passes the API key strictly via `x-goog-api-key` header (never in URL query string).
    """

    GEMINI_TTS_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        http_poster: Optional[Callable[[str, Dict[str, str], Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.http_poster = http_poster or self._default_http_poster

    @staticmethod
    def _default_http_poster(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def build_endpoint(self) -> str:
        if self.llm_config.tts_url.strip():
            return self.llm_config.tts_url.strip()
        model = self.llm_config.tts_model or "gemini-2.5-flash-preview-tts"
        model_path = model if model.startswith("models/") else f"models/{model}"
        return f"{self.GEMINI_TTS_BASE}/{model_path}:generateContent"

    def build_payload(self, sentence_text: str) -> Dict[str, Any]:
        voice_name = self.llm_config.voice_name or DEFAULT_VOICE_NAME
        return {
            "contents": [{"parts": [{"text": sentence_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name,
                        }
                    }
                },
            },
        }

    def synthesize(self, sentence_text: str, sample_rate: int = 24000) -> bytes:
        api_key = self.llm_config.api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key and not self.llm_config.tts_url.strip():
            return generate_synthetic_pcm(duration_s=0.25, sample_rate=sample_rate)

        url = self.build_endpoint()
        headers = {"x-goog-api-key": api_key} if api_key else {}
        res = self.http_poster(url, headers, self.build_payload(sentence_text))

        candidates = res.get("candidates") or []
        for cand in candidates:
            content = cand.get("content") or {}
            for part in content.get("parts") or []:
                inline = part.get("inlineData") or {}
                b64_audio = inline.get("data")
                if b64_audio:
                    return base64.b64decode(b64_audio)
        return generate_synthetic_pcm(duration_s=0.25, sample_rate=sample_rate)


class KokoroTTSAdapter:
    """
    Per-sentence Kokoro TTS adapter (`tts_engine == "kokoro"`) for T6.4 (`Issue #40`).
    Supports:
    1. Local/remote Kokoro HTTP server (`tts_url`, e.g. `POST /v1/audio/speech` returning 24 kHz PCM16).
    2. Local in-process `kokoro_onnx` / `kokoro` Python pipeline when installed.
    3. Graceful fallback to `generate_synthetic_pcm` when offline/unconfigured in unit tests.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        http_poster: Optional[Callable[[str, Dict[str, str], Dict[str, Any]], bytes]] = None,
        local_synthesizer: Optional[Callable[[str, str, int], bytes]] = None,
    ):
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.http_poster = http_poster or self._default_http_poster
        self.local_synthesizer = local_synthesizer

    @staticmethod
    def _default_http_poster(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return resp.read()

    def synthesize(self, sentence_text: str, sample_rate: int = 24000) -> bytes:
        voice = self.llm_config.voice_name or "am_michael"
        if self.local_synthesizer is not None:
            return self.local_synthesizer(sentence_text, voice, sample_rate)

        if self.llm_config.tts_url.strip():
            payload = {
                "model": self.llm_config.tts_model or "kokoro",
                "input": sentence_text,
                "voice": voice,
                "response_format": "pcm",
                "sample_rate": sample_rate,
            }
            headers: Dict[str, str] = {}
            if self.llm_config.api_key.strip():
                headers["Authorization"] = f"Bearer {self.llm_config.api_key.strip()}"
            raw = self.http_poster(self.llm_config.tts_url.strip(), headers, payload)
            if raw:
                return raw

        return generate_synthetic_pcm(duration_s=0.25, sample_rate=sample_rate)


class SubscriptionBrainAdapter:
    """
    Executes GOTCHI push-to-talk LLM reasoning turns over the regular `agy` or `claude`
    subscription (`auth_mode == "subscription"`), keeping LLM calls off metered API keys
    while pairing with `WhisperSTTAdapter` and `GeminiTTSAdapter` (`voice_name="Schedar"`) or `KokoroTTSAdapter`.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        stt_adapter: Optional[WhisperSTTAdapter] = None,
        cli_runner: Optional[Callable[[List[str], bytes], Any]] = None,
        http_poster: Optional[Callable[[str, Dict[str, str], Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.llm_config = llm_config
        self.stt_adapter = stt_adapter or WhisperSTTAdapter(llm_config=llm_config)
        self.cli_runner = cli_runner
        self.http_poster = http_poster

    async def __call__(self, parsed_turn: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        if parsed_turn.get("prompt"):
            transcript = str(parsed_turn["prompt"])
        elif parsed_turn.get("audio_bytes"):
            transcript = await loop.run_in_executor(
                None, self.stt_adapter.transcribe, parsed_turn["audio_bytes"]
            )
        else:
            transcript = "Analyzing camera snapshot"
        stt_ms = int((time.monotonic() - t0) * 1000)

        payload: Dict[str, Any] = {
            "node_id": parsed_turn.get("node_id", "gotchi-device"),
            "session_id": parsed_turn.get("session_id", "sess-0"),
            "prompt": transcript,
            "has_image": bool(parsed_turn.get("image_bytes")),
            "burst_count": len(parsed_turn.get("burst_images") or []),
        }
        if parsed_turn.get("image_bytes"):
            payload["image_b64"] = base64.b64encode(parsed_turn["image_bytes"]).decode("ascii")

        cmd = self.llm_config.subscription_command.strip()
        if cmd:
            validate_subscription_command(cmd)
            argv = shlex.split(cmd)
            stdin_bytes = json.dumps(payload).encode("utf-8")
            if self.cli_runner is not None:
                res_raw = self.cli_runner(argv, stdin_bytes)
                if inspect.isawaitable(res_raw):
                    res_raw = await res_raw
            else:
                from backend.live_gateway import _default_cli_runner

                res_raw = await _default_cli_runner(argv, stdin_bytes)
            text_out = (
                res_raw.decode("utf-8", errors="replace").strip()
                if isinstance(res_raw, (bytes, bytearray))
                else str(res_raw).strip()
            )
            try:
                parsed_json = json.loads(text_out)
                reply = str(
                    parsed_json.get("reply")
                    or parsed_json.get("text")
                    or parsed_json.get("result")
                    or text_out
                )
            except json.JSONDecodeError:
                reply = text_out
            return {"transcript": transcript, "reply": reply, "stt_ms": stt_ms}

        sub_url = self.llm_config.subscription_url.strip()
        if sub_url:
            headers: Dict[str, str] = {}
            if self.llm_config.session_token.strip():
                headers["Authorization"] = f"Bearer {self.llm_config.session_token.strip()}"
            if self.http_poster is not None:
                data = self.http_poster(sub_url, headers, payload)
            else:
                from backend.live_gateway import _default_http_json_post

                data = await loop.run_in_executor(
                    None, _default_http_json_post, sub_url, headers, payload
                )
            reply = str(data.get("reply") or data.get("text") or "")
            return {"transcript": transcript, "reply": reply, "stt_ms": stt_ms}

        return {"transcript": transcript, "reply": "Subscription reply ready.", "stt_ms": stt_ms}


def build_sse_event(event: str, data: dict) -> str:
    """Format single SSE message with event type and JSON payload."""
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def _read_part_bytes(val: Any) -> Optional[bytes]:
    """Read raw bytes from an uploaded multipart field without truthiness fallback bugs."""
    if val is None:
        return None
    file_obj = getattr(val, "file", None)
    if file_obj is not None:
        raw = file_obj.read()
    else:
        raw = val
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return None


def _default_webhook_poster(url: str, payload: Dict[str, Any]) -> None:
    """
    Default HTTP JSON POST dispatcher for DiscordVoiceSink.
    Enforces `https://` and `ALLOWED_DISCORD_WEBHOOK_HOSTS` before opening the connection.
    """
    validate_discord_webhook_url(url)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        resp.read()


class DiscordVoiceSink:
    """
    Configurable Discord Voice & BLE audio sink adapter for T3.3 (`audio_out_mode == "discord_voice"`).
    Routes 24 kHz PCM chunks to the configured bot (`zero` | `mirrormere` | `custom`) and POSTs to
    `discord_voice_webhook_url` via `loop.run_in_executor` so the asyncio event loop is never blocked.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        webhook_poster: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ):
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.webhook_poster = webhook_poster or _default_webhook_poster
        self.dispatched_chunks: List[Dict[str, Any]] = []

    def _build_event(
        self,
        mode: str,
        node_id: str,
        pcm_bytes: bytes,
        sample_rate: int,
        reply_text: str,
    ) -> Dict[str, Any]:
        event = {
            "mode": mode,
            "bot": self.llm_config.discord_voice_bot,
            "webhook_url": self.llm_config.discord_voice_webhook_url,
            "node_id": node_id,
            "pcm_bytes": len(pcm_bytes),
            "sample_rate": sample_rate,
            "reply_text": reply_text,
        }
        self.dispatched_chunks.append(event)
        return event

    def dispatch(
        self,
        mode: str,
        node_id: str,
        pcm_bytes: bytes,
        sample_rate: int,
        reply_text: str,
    ) -> Dict[str, Any]:
        event = self._build_event(mode, node_id, pcm_bytes, sample_rate, reply_text)
        url = self.llm_config.discord_voice_webhook_url.strip()
        if mode == "discord_voice" and url:
            validate_discord_webhook_url(url)
            self.webhook_poster(
                url,
                {
                    **event,
                    "audio_b64": base64.b64encode(pcm_bytes).decode("ascii"),
                },
            )
        return event

    async def adispatch(
        self,
        mode: str,
        node_id: str,
        pcm_bytes: bytes,
        sample_rate: int,
        reply_text: str,
    ) -> Dict[str, Any]:
        """Async dispatch running blocking webhook HTTP POST in the default executor."""
        event = self._build_event(mode, node_id, pcm_bytes, sample_rate, reply_text)
        url = self.llm_config.discord_voice_webhook_url.strip()
        if mode == "discord_voice" and url:
            validate_discord_webhook_url(url)
            payload = {
                **event,
                "audio_b64": base64.b64encode(pcm_bytes).decode("ascii"),
            }
            if inspect.iscoroutinefunction(self.webhook_poster):
                await self.webhook_poster(url, payload)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.webhook_poster, url, payload)
        return event


class VoiceGatewayService:
    """Core domain logic for parsing GOTCHI multipart turns and generating SSE events."""

    VALID_AUDIO_OUT_MODES = ("speaker", "discord_voice", "ble_phone")

    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        auth_required: bool = False,
        admin_token: Optional[str] = None,
        default_reply_text: str = "Gotchi voice response verified. System ready.",
        mock_sample_rate: int = 24000,
        event_format: str = "sentence",
        turn_handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
        tts_synthesizer: Optional[Callable[[str, int], bytes]] = None,
        audio_sink_router: Optional[Callable[[str, str, bytes, int, str], None]] = None,
        llm_config: Optional[LLMConfig] = None,
        discord_sink: Optional[DiscordVoiceSink] = None,
        stt_adapter: Optional[WhisperSTTAdapter] = None,
        gemini_tts: Optional[GeminiTTSAdapter] = None,
        kokoro_tts: Optional[KokoroTTSAdapter] = None,
        subscription_brain: Optional[SubscriptionBrainAdapter] = None,
    ):
        self.verifier = verifier or BearerTokenVerifier.from_env_or_file()
        self.auth_required = auth_required or bool(self.verifier.device_tokens)
        self.admin_token = (
            admin_token
            if admin_token is not None
            else os.environ.get("GOTCHI_ADMIN_TOKEN", "").strip()
        )
        self.default_reply_text = default_reply_text
        self.mock_sample_rate = mock_sample_rate
        self.event_format = event_format
        self.turn_handler = turn_handler
        self.tts_synthesizer = tts_synthesizer
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.discord_sink = discord_sink or DiscordVoiceSink(llm_config=self.llm_config)
        self.stt_adapter = stt_adapter or WhisperSTTAdapter(llm_config=self.llm_config)
        self.gemini_tts = gemini_tts or GeminiTTSAdapter(llm_config=self.llm_config)
        self.kokoro_tts = kokoro_tts or KokoroTTSAdapter(llm_config=self.llm_config)
        self.subscription_brain = subscription_brain or SubscriptionBrainAdapter(
            llm_config=self.llm_config,
            stt_adapter=self.stt_adapter,
        )
        self.audio_sink_router = audio_sink_router
        self.routed_audio_events: List[Dict[str, Any]] = []
        self.turn_timings: List[Dict[str, Any]] = []
        self.interactions_count = 0
        self.tts_fallback_cooldown_s: float = 600.0
        self._gemini_tts_backoff_until: float = 0.0

    def verify_admin_auth(self, headers: Mapping[str, str]) -> Tuple[bool, int, Dict[str, Any]]:
        """
        Requires a dedicated gateway admin token (`GOTCHI_ADMIN_TOKEN`) on `/api/config/llm`.
        Standard per-unit device tokens in `verifier.device_tokens` are rejected.
        """
        configured_admin = (self.admin_token or "").strip()
        if not configured_admin:
            return (
                False,
                401,
                {
                    "ok": False,
                    "error": "admin_token_required",
                    "message": "GOTCHI_ADMIN_TOKEN must be configured on the gateway for /api/config/llm",
                },
            )

        lower_headers = {k.lower(): v for k, v in headers.items()}
        candidate = lower_headers.get("x-gotchi-admin-token", "").strip()
        if not candidate:
            auth_hdr = lower_headers.get("authorization", "").strip()
            if auth_hdr.lower().startswith("bearer "):
                candidate = auth_hdr[7:].strip()

        if not candidate:
            return (
                False,
                401,
                {
                    "ok": False,
                    "error": "unauthorized",
                    "message": "Admin token is required for /api/config/llm",
                },
            )

        if not hmac.compare_digest(candidate.encode("utf-8"), configured_admin.encode("utf-8")):
            return (
                False,
                403,
                {
                    "ok": False,
                    "error": "forbidden",
                    "message": "Invalid admin token (device tokens are not permitted on /api/config/llm)",
                },
            )

        return True, 200, {"ok": True}

    def _synthesize_sentence_pcm(self, sentence_text: str) -> bytes:
        if self.tts_synthesizer is not None:
            return self.tts_synthesizer(sentence_text, self.mock_sample_rate)
        if self.llm_config.tts_engine == "gemini":
            now = time.monotonic()
            if now < self._gemini_tts_backoff_until:
                return self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
            try:
                return self.gemini_tts.synthesize(sentence_text, self.mock_sample_rate)
            except Exception as exc:
                logger.warning(
                    "Gemini TTS failed (%s); falling back to local Kokoro TTS for %.0fs",
                    exc,
                    self.tts_fallback_cooldown_s,
                )
                self._gemini_tts_backoff_until = now + self.tts_fallback_cooldown_s
                return self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
        if self.llm_config.tts_engine == "kokoro":
            return self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
        return generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate)

    def parse_multipart_data(
        self,
        form_data: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract audio, images (single or burst), node_id, session_id, prompt, audio_out_mode.
        Validates `node_id` (`^[A-Za-z0-9_-]{1,64}$`), rejects empty (`0-byte`) uploaded files,
        and rejects invalid `audio_out_mode` values.
        """
        raw_node_id = form_data.get("node_id") or "gotchi-device"
        node_id = validate_node_id(str(raw_node_id))
        session_id = form_data.get("session_id") or f"sess-{int(time.time()*1000)}"
        prompt = form_data.get("prompt")
        audio_out_mode = str(form_data.get("audio_out_mode") or "speaker")
        if audio_out_mode not in self.VALID_AUDIO_OUT_MODES:
            raise ValueError(
                f"Invalid audio_out_mode '{audio_out_mode}'; expected speaker | discord_voice | ble_phone"
            )

        audio_bytes: Optional[bytes] = None
        if "audio" in form_data:
            raw_audio = _read_part_bytes(form_data["audio"])
            if raw_audio is None or len(raw_audio) == 0:
                raise ValueError("Uploaded 'audio' part is empty (0 bytes)")
            audio_bytes = raw_audio

        image_bytes: Optional[bytes] = None
        if "image" in form_data:
            raw_img = _read_part_bytes(form_data["image"])
            if raw_img is None or len(raw_img) == 0:
                raise ValueError("Uploaded 'image' part is empty (0 bytes)")
            image_bytes = raw_img

        burst_images: List[bytes] = []
        for i in range(5):
            k = f"image_{i}"
            if k in form_data:
                raw_b = _read_part_bytes(form_data[k])
                if raw_b is None or len(raw_b) == 0:
                    raise ValueError(f"Uploaded '{k}' part is empty (0 bytes)")
                burst_images.append(raw_b)

        if not audio_bytes and not image_bytes and not burst_images:
            raise ValueError("Interaction must contain at least non-empty audio or image payload")

        mode = str(form_data.get("mode") or "interact").strip().lower()
        if mode not in ("interact", "journal"):
            raise ValueError(f"Invalid mode '{mode}'; expected interact | journal")

        return {
            "node_id": node_id,
            "session_id": str(session_id),
            "mode": mode,
            "prompt": str(prompt) if prompt is not None else None,
            "audio_out_mode": str(audio_out_mode),
            "audio_bytes": audio_bytes,
            "image_bytes": image_bytes,
            "burst_images": burst_images,
        }

    async def _invoke_turn_handler(self, parsed_turn: Dict[str, Any]) -> Dict[str, Any]:
        handler = self.turn_handler
        if handler is None and self.llm_config.auth_mode == "subscription":
            handler = self.subscription_brain
        if inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(getattr(handler, "__call__", None)):
            return await handler(parsed_turn)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, handler, parsed_turn)

    async def generate_sse_stream(
        self,
        parsed_turn: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Generate SSE event stream matching docs/MIRRORMERE_VOICE_CLIENT.md and PRD Section 5c."""
        self.interactions_count += 1
        t_start = time.monotonic()
        node_id = parsed_turn.get("node_id", "gotchi-device")
        session_id = parsed_turn.get("session_id", "sess-0")
        audio_out_mode = parsed_turn.get("audio_out_mode", "speaker")

        yield build_sse_event("turn", {"turn_id": session_id})
        yield build_sse_event("state", {"state": "transcribing"})
        await asyncio.sleep(0.005)

        has_images = bool(parsed_turn.get("image_bytes") or parsed_turn.get("burst_images"))
        has_prompt = parsed_turn.get("prompt") is not None
        active_handler = self.turn_handler or (
            self.subscription_brain if self.llm_config.auth_mode == "subscription" else None
        )

        # Pre-check voiced audio duration for audio-only turns without a custom turn_handler
        if active_handler is None:
            if parsed_turn.get("audio_bytes") and has_prompt:
                transcript_text = parsed_turn["prompt"]
            elif parsed_turn.get("audio_bytes"):
                if (
                    self.llm_config.stt_engine in ("whisper_http", "faster_whisper")
                    or self.stt_adapter.local_transcriber is not None
                ):
                    loop = asyncio.get_running_loop()
                    transcript_text = await loop.run_in_executor(
                        None, self.stt_adapter.transcribe, parsed_turn["audio_bytes"]
                    )
                else:
                    transcript_text = "What is the status?"
            elif has_prompt:
                transcript_text = parsed_turn["prompt"]
            elif parsed_turn.get("burst_images"):
                transcript_text = "Analyzing 5-frame burst capture"
            else:
                transcript_text = "Analyzing camera snapshot"

            is_ghost, ghost_reason = is_stt_ghost(
                transcript_text=transcript_text,
                audio_bytes=parsed_turn.get("audio_bytes"),
                min_voiced_ms=self.llm_config.min_voiced_ms,
                has_explicit_prompt=has_prompt,
                has_images=has_images,
            )
            stt_ms = int((time.monotonic() - t_start) * 1000)
            if is_ghost:
                total_ms = int((time.monotonic() - t_start) * 1000)
                timing_entry = {
                    "node_id": node_id,
                    "session_id": session_id,
                    "stt_ms": stt_ms,
                    "first_text_ms": -1,
                    "first_audio_ms": -1,
                    "total_ms": total_ms,
                    "ghost_filtered": True,
                    "ghost_reason": ghost_reason,
                }
                self.turn_timings.append(timing_entry)
                logger.info(
                    "turn_timing node_id=%s session_id=%s stt_ms=%d first_text_ms=-1 first_audio_ms=-1 total_ms=%d ghost_filtered=true reason=%s",
                    node_id,
                    session_id,
                    stt_ms,
                    total_ms,
                    ghost_reason,
                )
                yield build_sse_event(
                    "status",
                    {"status": "ghost_filtered", "reason": ghost_reason},
                )
                yield build_sse_event(
                    "done",
                    {
                        "duration_ms": total_ms,
                        "ghost_filtered": True,
                        "reason": ghost_reason,
                        "stt_ms": stt_ms,
                        "total_ms": total_ms,
                    },
                )
                return

            yield build_sse_event(
                "transcript",
                {"text": transcript_text, "transcript": transcript_text, "speaker": "ryan"},
            )
            await asyncio.sleep(0.005)
            yield build_sse_event("state", {"state": "thinking"})
            yield build_sse_event("thinking", {"elapsed_seconds": 1})
            await asyncio.sleep(0.005)

            if parsed_turn.get("burst_images"):
                reply_text = f"Received 5-frame burst ({len(parsed_turn['burst_images'])} images). Object tracking confirmed."
            elif parsed_turn.get("image_bytes"):
                reply_text = "Camera snapshot received. Identification verified."
            else:
                reply_text = self.default_reply_text
            explicit_pcm_chunks = None
            first_audio_ms: Optional[int] = None
        else:
            # Custom turn_handler path: run in background task and emit spoken filler at 1200ms / 5000ms
            yield build_sse_event("state", {"state": "thinking"})
            brain_start = time.monotonic()
            handler_task = asyncio.create_task(self._invoke_turn_handler(parsed_turn))
            filler_1_sent = False
            filler_2_sent = False
            first_audio_ms = None
            filler_1_s = self.llm_config.filler_delay_ms / 1000.0
            filler_2_s = self.llm_config.second_filler_delay_ms / 1000.0

            while not handler_task.done():
                elapsed_s = time.monotonic() - brain_start
                if (
                    self.llm_config.filler_delay_ms > 0
                    and not filler_1_sent
                    and elapsed_s >= filler_1_s
                ):
                    filler_1_sent = True
                    filler_pcm = self._synthesize_sentence_pcm("One moment.")
                    if first_audio_ms is None:
                        first_audio_ms = int((time.monotonic() - t_start) * 1000)
                    yield build_sse_event(
                        "sentence",
                        {
                            "text": "One moment.",
                            "filler": True,
                            "engine": "kokoro",
                            "format": "pcm",
                            "sample_rate": self.mock_sample_rate,
                            "channels": 1,
                            "is_final": False,
                            "audio_out_mode": audio_out_mode,
                            "audio_b64": base64.b64encode(filler_pcm).decode("ascii"),
                        },
                    )
                if (
                    self.llm_config.second_filler_delay_ms > 0
                    and not filler_2_sent
                    and elapsed_s >= filler_2_s
                ):
                    filler_2_sent = True
                    filler_pcm_2 = self._synthesize_sentence_pcm("Still working on that.")
                    yield build_sse_event(
                        "sentence",
                        {
                            "text": "Still working on that.",
                            "filler": True,
                            "engine": "kokoro",
                            "format": "pcm",
                            "sample_rate": self.mock_sample_rate,
                            "channels": 1,
                            "is_final": False,
                            "audio_out_mode": audio_out_mode,
                            "audio_b64": base64.b64encode(filler_pcm_2).decode("ascii"),
                        },
                    )
                try:
                    await asyncio.wait_for(asyncio.shield(handler_task), timeout=0.02)
                except asyncio.TimeoutError:
                    continue

            result = await handler_task
            stt_ms = int(result.get("stt_ms", (time.monotonic() - t_start) * 1000))
            transcript_text = result.get("transcript", parsed_turn.get("prompt") or "")

            is_ghost, ghost_reason = is_stt_ghost(
                transcript_text=transcript_text,
                audio_bytes=parsed_turn.get("audio_bytes"),
                min_voiced_ms=self.llm_config.min_voiced_ms,
                has_explicit_prompt=has_prompt,
                has_images=has_images,
            )
            if is_ghost:
                total_ms = int((time.monotonic() - t_start) * 1000)
                timing_entry = {
                    "node_id": node_id,
                    "session_id": session_id,
                    "stt_ms": stt_ms,
                    "first_text_ms": -1,
                    "first_audio_ms": -1 if first_audio_ms is None else first_audio_ms,
                    "total_ms": total_ms,
                    "ghost_filtered": True,
                    "ghost_reason": ghost_reason,
                }
                self.turn_timings.append(timing_entry)
                logger.info(
                    "turn_timing node_id=%s session_id=%s stt_ms=%d first_text_ms=-1 first_audio_ms=%d total_ms=%d ghost_filtered=true reason=%s",
                    node_id,
                    session_id,
                    stt_ms,
                    -1 if first_audio_ms is None else first_audio_ms,
                    total_ms,
                    ghost_reason,
                )
                yield build_sse_event(
                    "status",
                    {"status": "ghost_filtered", "reason": ghost_reason},
                )
                yield build_sse_event(
                    "done",
                    {
                        "duration_ms": total_ms,
                        "ghost_filtered": True,
                        "reason": ghost_reason,
                        "stt_ms": stt_ms,
                        "total_ms": total_ms,
                    },
                )
                return

            yield build_sse_event(
                "transcript",
                {"text": transcript_text, "transcript": transcript_text, "speaker": "ryan"},
            )
            reply_text = result.get("reply", self.default_reply_text)
            explicit_pcm_chunks = result.get("pcm_chunks")

        # Apply PRD Section 5c spoken reply word cap (default 60 words)
        reply_text = cap_reply_words(reply_text, max_words=self.llm_config.reply_cap_words)
        first_text_ms = int((time.monotonic() - t_start) * 1000)

        active_tts_engine = self.llm_config.tts_engine or "kokoro"
        active_voice_name = self.llm_config.voice_name or DEFAULT_VOICE_NAME

        yield build_sse_event("state", {"state": "synthesizing"})
        yield build_sse_event(
            "reply",
            {
                "reply": reply_text,
                "tts_engine": active_tts_engine,
                "voice_name": active_voice_name,
            },
        )
        await asyncio.sleep(0.005)

        yield build_sse_event("state", {"state": "speaking"})

        sentences = split_into_sentences(reply_text)
        if explicit_pcm_chunks is not None:
            sentence_pairs = [
                (sentences[idx] if idx < len(sentences) else "", chunk)
                for idx, chunk in enumerate(explicit_pcm_chunks)
            ]
        else:
            loop = asyncio.get_running_loop()
            sentence_pairs = []
            for sent in sentences:
                pcm_bytes = await loop.run_in_executor(None, self._synthesize_sentence_pcm, sent)
                sentence_pairs.append((sent, pcm_bytes))

        for idx, (sent_text, raw_pcm) in enumerate(sentence_pairs):
            is_final = (idx == len(sentence_pairs) - 1)
            b64_pcm = base64.b64encode(raw_pcm).decode("ascii")
            if first_audio_ms is None:
                first_audio_ms = int((time.monotonic() - t_start) * 1000)

            if audio_out_mode in ("discord_voice", "ble_phone"):
                sink_event = await self.discord_sink.adispatch(
                    audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, sent_text or reply_text
                )
                if self.audio_sink_router is not None:
                    self.audio_sink_router(
                        audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, sent_text or reply_text
                    )
                self.routed_audio_events.append({
                    "mode": audio_out_mode,
                    "bot": sink_event["bot"],
                    "node_id": node_id,
                    "chunk_index": idx,
                    "pcm_bytes": len(raw_pcm),
                    "sample_rate": self.mock_sample_rate,
                })
            if self.event_format == "sentence":
                yield build_sse_event(
                    "sentence",
                    {
                        "text": sent_text,
                        "sentence_index": idx,
                        "engine": active_tts_engine,
                        "voice_name": active_voice_name,
                        "format": "pcm",
                        "sample_rate": self.mock_sample_rate,
                        "channels": 1,
                        "is_final": is_final,
                        "audio_out_mode": audio_out_mode,
                        "audio_b64": b64_pcm,
                    },
                )
            else:
                yield build_sse_event(
                    "audio_chunk",
                    {
                        "chunk_index": idx,
                        "format": "pcm",
                        "sample_rate": self.mock_sample_rate,
                        "channels": 1,
                        "is_final": is_final,
                        "audio_out_mode": audio_out_mode,
                        "data": b64_pcm,
                    },
                )
            await asyncio.sleep(0.005)

        total_ms = int((time.monotonic() - t_start) * 1000)
        if first_audio_ms is None:
            first_audio_ms = total_ms
        timing_entry = {
            "node_id": node_id,
            "session_id": session_id,
            "stt_ms": stt_ms,
            "first_text_ms": first_text_ms,
            "first_audio_ms": first_audio_ms,
            "total_ms": total_ms,
            "ghost_filtered": False,
        }
        self.turn_timings.append(timing_entry)
        logger.info(
            "turn_timing node_id=%s session_id=%s stt_ms=%d first_text_ms=%d first_audio_ms=%d total_ms=%d ghost_filtered=false",
            node_id,
            session_id,
            stt_ms,
            first_text_ms,
            first_audio_ms,
            total_ms,
        )
        yield build_sse_event(
            "done",
            {
                "duration_ms": total_ms,
                "stt_ms": stt_ms,
                "first_text_ms": first_text_ms,
                "first_audio_ms": first_audio_ms,
                "total_ms": total_ms,
            },
        )


def create_app(
    service: Optional[VoiceGatewayService] = None,
    live_service: Optional[Any] = None,
    journal_service: Optional[Any] = None,
) -> "FastAPI":
    """Factory to create FastAPI instance with /api/voice/interact, /api/live/ws, /api/journal/*, and /api/config/llm."""
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed")

    from backend.live_gateway import LiveGatewayService, register_live_routes
    from backend.journal_service import JournalService, register_journal_routes

    app = FastAPI(title="Gotchi Reference Voice Gateway")
    srv = service or VoiceGatewayService()
    live_srv = live_service or LiveGatewayService(
        verifier=srv.verifier,
        auth_required=srv.auth_required,
        llm_config=srv.llm_config,
    )
    journal_srv = journal_service or JournalService(
        verifier=srv.verifier,
        auth_required=srv.auth_required,
        min_voiced_ms=srv.llm_config.min_voiced_ms,
    )
    app.state.journal_service = journal_srv

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "gotchi-voice-gateway",
            "live_mode_enabled": live_srv.is_enabled(),
            "llm_config": srv.llm_config.to_public_dict(),
        }

    @app.get("/api/config/voices")
    def get_voice_options():
        return {
            "ok": True,
            "default_voice": DEFAULT_VOICE_NAME,
            "active_voice": srv.llm_config.voice_name,
            "active_tts_engine": srv.llm_config.tts_engine,
            "gemini_hd_voices": list(GEMINI_HD_VOICES),
            "kokoro_voices": list(KOKORO_VOICES),
        }

    @app.get("/api/config/llm")
    def get_llm_config(request: Request):
        ok, code, err = srv.verify_admin_auth(request.headers)
        if not ok:
            return JSONResponse(status_code=code, content=err)
        return {"ok": True, "llm_config": srv.llm_config.to_public_dict()}

    @app.put("/api/config/llm")
    @app.post("/api/config/llm")
    async def update_llm_config(request: Request):
        ok, code, err = srv.verify_admin_auth(request.headers)
        if not ok:
            return JSONResponse(status_code=code, content=err)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            srv.llm_config.update_from_dict(body)
        except ValueError as ve:
            return JSONResponse(
                status_code=400, content={"ok": False, "error": "bad_request", "message": str(ve)}
            )
        except Exception as exc:
            return JSONResponse(
                status_code=400, content={"ok": False, "error": "bad_request", "message": str(exc)}
            )
        return {"ok": True, "llm_config": srv.llm_config.to_public_dict()}

    @app.post("/api/voice/interact")
    async def voice_interact(
        request: Request,
        authorization: Optional[str] = Header(None),
    ):
        headers = dict(request.headers)
        client_ip = request.client.host if request.client else "0.0.0.0"

        if srv.auth_required or srv.verifier.device_tokens:
            ok, code, err = srv.verifier.verify(headers, client_ip=client_ip)
            if not ok:
                return JSONResponse(status_code=code, content=err)

        try:
            form = await request.form()
            parsed_turn = srv.parse_multipart_data(form)
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(ve)})
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": "bad_request", "message": f"Multipart parse error: {e}"})

        if parsed_turn.get("mode") == "journal":
            j_res = journal_srv.ingest_segment(
                node_id=parsed_turn["node_id"],
                audio_bytes=parsed_turn.get("audio_bytes"),
                transcript=parsed_turn.get("prompt"),
                session_id=parsed_turn.get("session_id"),
                transport="ble_or_wifi_interact",
            )

            async def _journal_sse() -> AsyncGenerator[str, None]:
                yield build_sse_event("status", {"status": "journal_logged", "journal": j_res})
                yield build_sse_event("done", {"mode": "journal", "journal": j_res})

            return StreamingResponse(
                _journal_sse(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        generator = srv.generate_sse_stream(parsed_turn)
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    register_live_routes(app, live_srv)
    register_journal_routes(app, journal_srv)
    return app
