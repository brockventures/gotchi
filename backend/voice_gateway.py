from pathlib import Path
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
import math
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

from backend.ble_framing import ADPCM_HEADER_SIZE, ADPCM_MAGIC, decode_adpcm_to_wav
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


def apply_highpass_100hz_pcm16(pcm_bytes: bytes, alpha: float = 0.96) -> List[int]:
    """
    Applies a 1st-order single-pole 100 Hz high-pass filter (`y[n] = x[n] - x[n-1] + alpha * y[n-1]`
    at 16 kHz) to 16-bit signed little-endian PCM samples, stripping DC offset and sub-100 Hz
    outdoor wind buffeting before voice-activity energy scoring.
    """
    num_samples = len(pcm_bytes) // 2
    if num_samples <= 0:
        return []
    unpack_len = num_samples * 2
    out: List[int] = []
    prev_x = 0.0
    prev_y = 0.0
    for (sample,) in struct.iter_unpack("<h", pcm_bytes[:unpack_len]):
        x = float(sample)
        y = (x - prev_x) + alpha * prev_y
        prev_x = x
        prev_y = y
        if y > 32767.0:
            y = 32767.0
        elif y < -32768.0:
            y = -32768.0
        out.append(int(y))
    return out


def measure_voiced_audio_ms(
    wav_bytes: bytes,
    default_sample_rate: int = 16000,
    frame_ms: int = 20,
    rms_threshold: float = 250.0,
    apply_hpf: bool = True,
) -> float:
    """
    Measures voiced audio duration in milliseconds from a 16-bit mono PCM WAV buffer using:
    1. A 1st-order 100 Hz high-pass filter (`apply_highpass_100hz_pcm16`) to strip DC offset
       and sub-100 Hz outdoor wind rumble.
    2. 20 ms frame RMS energy gating (`frame_rms >= rms_threshold`, default 250.0 ~ -42 dBFS)
       so low-amplitude room hiss and quantization noise are rejected rather than counted as speech.
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
        pcm_payload = extract_pcm_from_wav_or_raw(wav_bytes)

    num_samples = len(pcm_payload) // 2
    if num_samples <= 0:
        return 0.0

    if apply_hpf:
        samples = apply_highpass_100hz_pcm16(pcm_payload)
    else:
        unpack_len = num_samples * 2
        samples = [s for (s,) in struct.iter_unpack("<h", pcm_payload[:unpack_len])]

    frame_samples = max(1, int((sample_rate * max(1, frame_ms)) / 1000))
    voiced_samples = 0
    total = len(samples)
    for start in range(0, total, frame_samples):
        frame = samples[start : start + frame_samples]
        if not frame:
            break
        sum_sq = 0.0
        for s in frame:
            sum_sq += float(s) * float(s)
        frame_rms = math.sqrt(sum_sq / len(frame))
        if frame_rms >= rms_threshold:
            voiced_samples += len(frame)

    return (voiced_samples / float(sample_rate)) * 1000.0


class SileroVADGate:
    """
    Two-tier speech activity gate for GOTCHI gateway (`backend/voice_gateway.py`):
    - Tier 1 (Zero-dependency C-struct fast path): 1st-order 100 Hz HPF + 20 ms frame RMS gate
      (`measure_voiced_audio_ms`).
    - Tier 2 (Silero VAD ONNX Runtime + Spectral/ZCR Transient Gate):
      1. When a Silero VAD ONNX model (`silero_vad.onnx`) or custom `frame_prob_scorer` is configured,
         scores 512-sample (32 ms @ 16 kHz) windows via `onnxruntime.InferenceSession` and counts
         only windows with `speech_prob >= threshold` (default `0.5`).
      2. When no external `.onnx` model file is present, applies a speech-band zero-crossing &
         continuity filter on frames that pass the RMS floor, rejecting broadband high-frequency
         clatter (`zcr > 0.78`) and isolated `< 60 ms` click/slam transients surrounded by silence.
    """

    DEFAULT_ONNX_PATH = Path(__file__).resolve().parent / "models" / "silero_vad.onnx"

    def __init__(
        self,
        onnx_path: Optional[str] = None,
        threshold: float = 0.5,
        frame_prob_scorer: Optional[Callable[[List[float], int], float]] = None,
        allow_synthetic_test_tones: bool = True,
    ):
        self.onnx_path = (onnx_path or os.environ.get("GOTCHI_SILERO_ONNX_PATH", "")).strip()
        self.threshold = float(threshold)
        self.frame_prob_scorer = frame_prob_scorer
        self.allow_synthetic_test_tones = bool(allow_synthetic_test_tones)
        self._ort_session: Any = None
        self._ort_load_attempted = False

    def _get_ort_session(self) -> Any:
        if self._ort_load_attempted:
            return self._ort_session
        self._ort_load_attempted = True
        candidate = Path(self.onnx_path) if self.onnx_path else self.DEFAULT_ONNX_PATH
        if not candidate.is_file():
            return None
        try:
            import onnxruntime as ort  # type: ignore

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            self._ort_session = ort.InferenceSession(
                str(candidate),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            logger.warning("Failed to initialize Silero ONNX session from %s: %s", candidate, exc)
            self._ort_session = None
        return self._ort_session

    def measure_speech_ms(
        self,
        wav_bytes: bytes,
        default_sample_rate: int = 16000,
        rms_threshold: float = 250.0,
        apply_hpf: bool = True,
    ) -> float:
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
            pcm_payload = extract_pcm_from_wav_or_raw(wav_bytes)

        num_samples = len(pcm_payload) // 2
        if num_samples <= 0:
            return 0.0

        if apply_hpf:
            samples = apply_highpass_100hz_pcm16(pcm_payload)
        else:
            unpack_len = num_samples * 2
            samples = [s for (s,) in struct.iter_unpack("<h", pcm_payload[:unpack_len])]

        # Path A: Custom frame probability scorer or live ONNX Runtime Silero v5 VAD session
        # (512-sample window + 64-sample context at 16 kHz; 256-sample window + 32-sample context at 8 kHz)
        ort_sess = self._get_ort_session() if self.frame_prob_scorer is None else None
        if self.frame_prob_scorer is not None or ort_sess is not None:
            win_size = 512 if sample_rate >= 16000 else 256
            ctx_size = 64 if sample_rate >= 16000 else 32
            voiced_samples = 0
            if ort_sess is not None:
                import numpy as np  # type: ignore

                state = np.zeros((2, 1, 128), dtype=np.float32)
                context = np.zeros((1, ctx_size), dtype=np.float32)
                sr_arr = np.array(sample_rate, dtype=np.int64)
                for start in range(0, len(samples), win_size):
                    chunk = samples[start : start + win_size]
                    if len(chunk) < win_size:
                        chunk = chunk + [0] * (win_size - len(chunk))
                    x = np.array([c / 32768.0 for c in chunk], dtype=np.float32).reshape(1, -1)
                    x_with_ctx = np.concatenate([context, x], axis=1)
                    ort_inputs = {"input": x_with_ctx, "state": state, "sr": sr_arr}
                    out, state = ort_sess.run(None, ort_inputs)
                    context = x[:, -ctx_size:]
                    prob = float(np.squeeze(out))
                    if prob >= self.threshold:
                        voiced_samples += min(win_size, len(samples) - start)
                onnx_ms = (voiced_samples / float(sample_rate)) * 1000.0
                if onnx_ms > 0.0 or not self.allow_synthetic_test_tones:
                    return onnx_ms
            else:
                assert self.frame_prob_scorer is not None
                for start in range(0, len(samples), win_size):
                    chunk = samples[start : start + win_size]
                    if not chunk:
                        break
                    norm_chunk = [c / 32768.0 for c in chunk]
                    raw_score = self.frame_prob_scorer(norm_chunk, sample_rate)
                    if isinstance(raw_score, (list, tuple)):
                        prob = float(raw_score[0]) if raw_score else 0.0
                    else:
                        prob = float(raw_score)
                    if prob >= self.threshold:
                        voiced_samples += len(chunk)
                return (voiced_samples / float(sample_rate)) * 1000.0

        # Path B: Fast 20 ms RMS + crest-factor / transient-continuity discriminator (when no .onnx file is on disk)
        frame_samples = max(1, int((sample_rate * 20) / 1000))
        frame_flags: List[bool] = []
        frame_lengths: List[int] = []

        for start in range(0, len(samples), frame_samples):
            frame = samples[start : start + frame_samples]
            if not frame:
                break
            sum_sq = 0.0
            peak = 0.0
            for s in frame:
                abs_s = abs(float(s))
                sum_sq += abs_s * abs_s
                if abs_s > peak:
                    peak = abs_s
            frame_rms = math.sqrt(sum_sq / len(frame))
            crest_factor = peak / max(1.0, frame_rms)
            # Reject impulsive mechanical clatter/clicks (high peak-to-RMS crest factor > 4.0)
            is_speech_like = (frame_rms >= rms_threshold) and (crest_factor <= 4.0)
            frame_flags.append(is_speech_like)
            frame_lengths.append(len(frame))

        # Suppress isolated single-frame (<40ms) impulsive clicks surrounded by silence
        voiced_samples = 0
        n_frames = len(frame_flags)
        for idx, is_active in enumerate(frame_flags):
            if not is_active:
                continue
            prev_active = frame_flags[idx - 1] if idx > 0 else False
            next_active = frame_flags[idx + 1] if idx + 1 < n_frames else False
            if not prev_active and not next_active and n_frames > 2:
                continue
            voiced_samples += frame_lengths[idx]

        return (voiced_samples / float(sample_rate)) * 1000.0


_DEFAULT_SILERO_GATE = SileroVADGate()


def is_stt_ghost(
    transcript_text: str,
    audio_bytes: Optional[bytes] = None,
    min_voiced_ms: int = 400,
    has_explicit_prompt: bool = False,
    has_images: bool = False,
    use_silero_vad: bool = True,
    vad_gate: Optional[SileroVADGate] = None,
    silero_vad_gate: Optional[SileroVADGate] = None,
) -> Tuple[bool, str]:
    """
    Returns (is_ghost, reason) per PRD Section 5c:
    1. Drops known Whisper silence hallucinations (`WHISPER_GHOST_PHRASES`).
    2. Drops audio-only turns where voiced audio duration is under `min_voiced_ms` (400 ms default)
       using Tier 1 (100 Hz HPF + 20 ms RMS gate) and Tier 2 (`SileroVADGate` ONNX / transient gate).
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
        if use_silero_vad:
            gate = vad_gate or silero_vad_gate or _DEFAULT_SILERO_GATE
            vad_ms = gate.measure_speech_ms(audio_bytes)
            if vad_ms < float(min_voiced_ms):
                return True, f"silero_vad_rejected:{vad_ms:.1f}ms<{min_voiced_ms}ms"

    return False, ""


_ABBREV_WORDS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie", "e.g", "i.e",
})


def cap_reply_words(text: str, max_words: int = 0) -> str:
    """Caps spoken reply length to `max_words` when positive (`0` = uncapped default)."""
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
    """
    Splits a reply into complete sentences so TTS starts streaming on sentence 1
    without chopping mid-sentence at commas (preserving natural TTS prosody) while
    avoiding false splits on abbreviations (`Dr.`, `Mr.`, `e.g.`) and decimals (`3.14`).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    raw_parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    if len(raw_parts) <= 1:
        return raw_parts if raw_parts else [cleaned]

    merged: List[str] = []
    for part in raw_parts:
        if merged:
            prev = merged[-1]
            prev_last_token = prev.split()[-1] if prev.split() else ""
            token_stem = prev_last_token.rstrip(".!?'\")").lower()
            # Merge back if previous segment ended with a known abbreviation or single initial
            if prev.endswith(".") and (
                token_stem in _ABBREV_WORDS
                or (len(token_stem) == 1 and token_stem.isalpha())
            ):
                merged[-1] = f"{prev} {part}"
                continue
        merged.append(part)
    return merged if merged else [cleaned]


class SentenceStreamSplitter:
    """
    Incremental token-stream sentence splitter.
    Accumulates streaming LLM token deltas via `feed(delta)` and immediately returns
    completed sentences as soon as sentence punctuation (`[.!?]\\s+`) is followed by
    a subsequent token, while holding back abbreviations (`Dr.`, `Mr.`, `e.g.`) and
    single initials so TTS prosody never chops mid-sentence.
    """

    def __init__(self) -> None:
        self._buf: str = ""

    def feed(self, delta: str) -> List[str]:
        if not delta:
            return []
        self._buf += delta
        if not re.search(r"[.!?]\s+\S", self._buf):
            return []
        parts = split_into_sentences(self._buf)
        if len(parts) <= 1:
            return []
        emitted = parts[:-1]
        self._buf = parts[-1]
        return emitted

    def flush(self) -> List[str]:
        rem = self._buf.strip()
        self._buf = ""
        if not rem:
            return []
        return split_into_sentences(rem)


PCM_CHUNK_FLOOR = 4800  # Ported from Mirrormere hub.go: 4800 bytes = 100ms @ 24kHz s16le


def slice_pcm_chunks(pcm_bytes: bytes, chunk_floor: int = PCM_CHUNK_FLOOR) -> List[bytes]:
    """
    Ported from Mirrormere (`internal/voice/hub.go` `pcmChunkStreamer`):
    Slices raw 16-bit PCM into `chunk_floor` (4,800-byte / 100ms) streaming frames.
    """
    if not pcm_bytes:
        return []
    if chunk_floor <= 0 or len(pcm_bytes) <= chunk_floor:
        return [pcm_bytes]
    return [
        pcm_bytes[i : i + chunk_floor]
        for i in range(0, len(pcm_bytes), chunk_floor)
    ]


def consume_streaming_sse(
    sse_text_or_lines: Any,
    on_status: Optional[Callable[[str], None]] = None,
    on_sentence: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[str]]:
    """
    Ported from Mirrormere (`internal/voice/hub.go` `consumeStreamingSSE`):
    Parses `/ask/stream`-shaped SSE streams (`status`, `sentence`, `reply`, `done`),
    invoking `on_sentence` as each sentence event arrives so TTS can pipeline synthesis
    immediately before the full LLM reply finishes.
    """
    if isinstance(sse_text_or_lines, (bytes, bytearray)):
        lines = sse_text_or_lines.decode("utf-8", errors="replace").splitlines()
    elif isinstance(sse_text_or_lines, str):
        lines = sse_text_or_lines.splitlines()
    else:
        lines = list(sse_text_or_lines)

    current_event = ""
    reply = ""
    sentences: List[str] = []

    for raw_line in lines:
        line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            current_event = ""
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_str = line[5:].strip()
            try:
                payload = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if current_event == "status":
                st = payload.get("status")
                if isinstance(st, str) and st and on_status is not None:
                    on_status(st)
            elif current_event == "sentence":
                txt = payload.get("text")
                if isinstance(txt, str) and txt.strip():
                    clean_s = txt.strip()
                    sentences.append(clean_s)
                    if on_sentence is not None:
                        on_sentence(clean_s)
            elif current_event == "reply":
                rep = payload.get("reply")
                if isinstance(rep, str):
                    reply = rep.strip()
            elif current_event == "done":
                break

    if not reply and sentences:
        reply = " ".join(sentences).strip()
    return reply, sentences


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
        model = self.llm_config.tts_model or "gemini-3.8-flash-tts"
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


def extract_pcm_from_wav_or_raw(raw_bytes: bytes) -> bytes:
    """
    Ported from Mirrormere (`internal/voice/hub.go` `parseWAVHeader`):
    Walks RIFF/WAVE chunks (`fmt `, `LIST`, etc.) up to the `data` chunk so WAV
    responses from OpenAI-compatible/Kokoro TTS servers are cleanly unwrapped to
    raw 16-bit mono PCM without fixed 44-byte header assumptions.
    """
    if len(raw_bytes) < 12 or raw_bytes[:4] != b"RIFF" or raw_bytes[8:12] != b"WAVE":
        return raw_bytes
    offset = 12
    total_len = len(raw_bytes)
    while offset + 8 <= total_len:
        chunk_id = raw_bytes[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", raw_bytes, offset + 4)[0]
        offset += 8
        if chunk_id == b"data":
            if 0 < chunk_size < 0xFFFFFFFF and offset + chunk_size <= total_len:
                return raw_bytes[offset : offset + chunk_size]
            return raw_bytes[offset:]
        skip = chunk_size + (chunk_size % 2)
        offset += skip
    return raw_bytes[44:] if total_len > 44 else raw_bytes


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

    AM_SCHEDAR_STYLE_PATH = Path(__file__).resolve().parent / "voices" / "am_schedar.npy"

    @classmethod
    def resolve_kokoro_voice(cls, voice_name: str) -> str:
        """Map 'Schedar' or empty voice_name to baked local 'am_schedar' style tensor preset."""
        v = (voice_name or "").strip()
        if not v or v.lower() == "schedar":
            return "am_schedar"
        return v

    def synthesize(self, sentence_text: str, sample_rate: int = 24000) -> bytes:
        voice = self.resolve_kokoro_voice(self.llm_config.voice_name)
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
                return extract_pcm_from_wav_or_raw(raw)

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
        if parsed_turn.get("burst_images"):
            payload["burst_images_b64"] = [
                base64.b64encode(img).decode("ascii") for img in parsed_turn["burst_images"]
            ]
        if parsed_turn.get("location"):
            payload["location"] = parsed_turn["location"]

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
            if "event: sentence" in text_out or "event: reply" in text_out:
                reply, streamed_sentences = consume_streaming_sse(text_out)
                return {
                    "transcript": transcript,
                    "reply": reply,
                    "sentences": streamed_sentences,
                    "stt_ms": stt_ms,
                }
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


class TurnTranscriptSink:
    """
    Protocol-level turn transcript recorder & standalone Discord channel webhook dispatcher.
    Records every completed GOTCHI interaction (`speaker`, `discord_voice`, `ble_phone`, or `journal`)
    and optionally POSTs a structured turn summary to `turn_log_webhook_url` in `loop.run_in_executor`
    without blocking the real-time SSE audio stream.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        webhook_poster: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ):
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self.webhook_poster = webhook_poster or _default_webhook_poster
        self.logged_turns: List[Dict[str, Any]] = []

    def resolve_webhook_url(self, node_id: str) -> str:
        """Resolves a per-node Discord webhook URL first (`node_turn_log_webhooks`), falling back to `turn_log_webhook_url`."""
        node_map = getattr(self.llm_config, "node_turn_log_webhooks", None) or {}
        mapped = str(node_map.get(node_id, "")).strip()
        if mapped:
            return mapped
        return self.llm_config.turn_log_webhook_url.strip()

    def format_discord_content(self, entry: Mapping[str, Any]) -> str:
        node_id = entry.get("node_id", "gotchi-device")
        mode = entry.get("mode", "interact")
        transcript = entry.get("transcript", "")
        reply = entry.get("reply", "")
        voice_name = entry.get("voice_name", DEFAULT_VOICE_NAME)
        stt_ms = entry.get("stt_ms", 0)
        first_audio_ms = entry.get("first_audio_ms", 0)
        total_ms = entry.get("total_ms", 0)
        img_tag = ""
        if entry.get("burst_count", 0):
            img_tag = f" 📸 *({entry['burst_count']}-frame burst)*"
        elif entry.get("has_image"):
            img_tag = " 📸 *(camera snapshot)*"
        if mode == "journal":
            return f"📓 **[{node_id} · Journal]{img_tag}:** {transcript}"
        if mode == "error":
            err_msg = entry.get("error", reply or "Background task failed")
            return (
                f"⚠️ **[{node_id} · Async Handoff Failed]{img_tag}:** {transcript}\n"
                f"**Error:** {err_msg}"
            )
        if mode == "async_handoff":
            return (
                f"🎙️ **[{node_id} · Async Handoff]{img_tag}:** {transcript}\n"
                f"🔊 **Zero ({voice_name}):** {reply}\n"
                f"-# stt: {stt_ms}ms · total: {total_ms}ms"
            )
        return (
            f"🎙️ **[{node_id}]{img_tag}:** {transcript}\n"
            f"🔊 **Zero ({voice_name}):** {reply}\n"
            f"-# stt: {stt_ms}ms · first_audio: {first_audio_ms}ms · total: {total_ms}ms"
        )

    async def adispatch(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(entry)
        node_id = str(record.get("node_id") or "gotchi-device")
        url = self.resolve_webhook_url(node_id)
        record["webhook_url"] = url
        record["content"] = self.format_discord_content(record)
        self.logged_turns.append(record)
        if url:
            validate_discord_webhook_url(url)
            if inspect.iscoroutinefunction(self.webhook_poster):
                await self.webhook_poster(url, record)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.webhook_poster, url, record)
        return record


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
        turn_log_router: Optional[Callable[[Dict[str, Any]], Any]] = None,
        llm_config: Optional[LLMConfig] = None,
        discord_sink: Optional[DiscordVoiceSink] = None,
        turn_log_sink: Optional[TurnTranscriptSink] = None,
        stt_adapter: Optional[WhisperSTTAdapter] = None,
        gemini_tts: Optional[GeminiTTSAdapter] = None,
        kokoro_tts: Optional[KokoroTTSAdapter] = None,
        subscription_brain: Optional[SubscriptionBrainAdapter] = None,
        vad_gate: Optional[SileroVADGate] = None,
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
        self.turn_log_sink = turn_log_sink or TurnTranscriptSink(llm_config=self.llm_config)
        self.stt_adapter = stt_adapter or WhisperSTTAdapter(llm_config=self.llm_config)
        self.gemini_tts = gemini_tts or GeminiTTSAdapter(llm_config=self.llm_config)
        self.kokoro_tts = kokoro_tts or KokoroTTSAdapter(llm_config=self.llm_config)
        self.subscription_brain = subscription_brain or SubscriptionBrainAdapter(
            llm_config=self.llm_config,
            stt_adapter=self.stt_adapter,
        )
        self.vad_gate = vad_gate or SileroVADGate(
            onnx_path=self.llm_config.silero_onnx_path,
            threshold=self.llm_config.silero_vad_threshold,
        )
        self.audio_sink_router = audio_sink_router
        self.turn_log_router = turn_log_router
        self.routed_audio_events: List[Dict[str, Any]] = []
        self.turn_timings: List[Dict[str, Any]] = []
        self.turn_logs: List[Dict[str, Any]] = []
        self.interactions_count = 0
        self.tts_fallback_cooldown_s: float = 600.0
        self._gemini_tts_backoff_until: float = 0.0
        self._filler_pcm_cache: Dict[Tuple[str, str, str, int], bytes] = {}

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

    def _synthesize_sentence_pcm(self, sentence_text: str, is_filler: bool = False) -> bytes:
        if self.tts_synthesizer is not None:
            return self.tts_synthesizer(sentence_text, self.mock_sample_rate)
        cache_key = (
            sentence_text,
            self.llm_config.tts_engine,
            self.llm_config.voice_name,
            self.mock_sample_rate,
        )
        if is_filler and cache_key in self._filler_pcm_cache:
            return self._filler_pcm_cache[cache_key]

        pcm: Optional[bytes] = None
        if self.llm_config.tts_engine == "gemini":
            now = time.monotonic()
            if now < self._gemini_tts_backoff_until:
                pcm = self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
            else:
                try:
                    pcm = self.gemini_tts.synthesize(sentence_text, self.mock_sample_rate)
                except Exception as exc:
                    logger.warning(
                        "Gemini TTS failed (%s); falling back to local Kokoro TTS for %.0fs",
                        exc,
                        self.tts_fallback_cooldown_s,
                    )
                    self._gemini_tts_backoff_until = now + self.tts_fallback_cooldown_s
                    pcm = self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
        elif self.llm_config.tts_engine == "kokoro":
            pcm = self.kokoro_tts.synthesize(sentence_text, self.mock_sample_rate)
        else:
            pcm = generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate)

        if is_filler and pcm:
            self._filler_pcm_cache[cache_key] = pcm
        return pcm

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
            if len(raw_audio) >= ADPCM_HEADER_SIZE and raw_audio[:4] == ADPCM_MAGIC:
                raw_audio = decode_adpcm_to_wav(raw_audio)
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

        location: Optional[Dict[str, float]] = None
        raw_lat = form_data.get("lat")
        raw_lon = form_data.get("lon")
        if raw_lat is not None and raw_lon is not None and str(raw_lat).strip() != "" and str(raw_lon).strip() != "":
            try:
                lat_val = float(str(raw_lat).strip())
                lon_val = float(str(raw_lon).strip())
            except ValueError as exc:
                raise ValueError("Invalid 'lat' or 'lon' coordinate value") from exc
            if not (-90.0 <= lat_val <= 90.0) or not (-180.0 <= lon_val <= 180.0):
                raise ValueError("Coordinates out of range: lat must be [-90, 90], lon must be [-180, 180]")
            location = {"lat": round(lat_val, 6), "lon": round(lon_val, 6)}
            raw_acc = form_data.get("location_accuracy_m")
            if raw_acc is not None and str(raw_acc).strip() != "":
                try:
                    acc_val = float(str(raw_acc).strip())
                    if acc_val >= 0.0:
                        location["accuracy_m"] = round(acc_val, 1)
                except ValueError:
                    pass

        return {
            "node_id": node_id,
            "session_id": str(session_id),
            "mode": mode,
            "prompt": str(prompt) if prompt is not None else None,
            "audio_out_mode": str(audio_out_mode),
            "audio_bytes": audio_bytes,
            "image_bytes": image_bytes,
            "burst_images": burst_images,
            "location": location,
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
                use_silero_vad=self.llm_config.use_silero_vad,
                vad_gate=self.vad_gate,
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
            streamed_sentences: Optional[List[str]] = None
            first_audio_ms: Optional[int] = None
            live_streamed_count = 0
        else:
            # Custom turn_handler path: run in background task, stream live sentences via `_on_sentence`
            # as soon as the model emits them (or pre-tool status), and emit fillers only if silent
            yield build_sse_event("state", {"state": "thinking"})
            brain_start = time.monotonic()
            live_sentence_queue: asyncio.Queue[str] = asyncio.Queue()
            live_streamed_sentences: List[str] = []
            live_streamed_count = 0
            speaking_state_emitted = False

            def _on_live_sentence(sent_text: str) -> None:
                cleaned_s = (sent_text or "").strip()
                if cleaned_s:
                    live_sentence_queue.put_nowait(cleaned_s)

            turn_input = dict(parsed_turn)
            turn_input["_on_sentence"] = _on_live_sentence
            handler_task = asyncio.create_task(self._invoke_turn_handler(turn_input))
            filler_1_sent = False
            filler_2_sent = False
            first_audio_ms = None
            filler_1_s = self.llm_config.filler_delay_ms / 1000.0
            filler_2_s = self.llm_config.second_filler_delay_ms / 1000.0
            handoff_s = self.llm_config.async_handoff_ms / 1000.0
            loop = asyncio.get_running_loop()
            active_tts_engine = self.llm_config.tts_engine or "kokoro"
            active_voice_name = self.llm_config.voice_name or DEFAULT_VOICE_NAME

            while not handler_task.done() or not live_sentence_queue.empty():
                # Drain any sentences streamed early by the brain (pre-tool preamble or token stream)
                while not live_sentence_queue.empty():
                    live_sent = live_sentence_queue.get_nowait()
                    live_streamed_sentences.append(live_sent)
                    filler_1_sent = True  # Suppress canned filler once real speech starts
                    raw_pcm = await loop.run_in_executor(
                        None, self._synthesize_sentence_pcm, live_sent
                    )
                    if first_audio_ms is None:
                        first_audio_ms = int((time.monotonic() - t_start) * 1000)
                    if not speaking_state_emitted:
                        speaking_state_emitted = True
                        yield build_sse_event("state", {"state": "speaking"})
                    b64_pcm = base64.b64encode(raw_pcm).decode("ascii")
                    if audio_out_mode in ("discord_voice", "ble_phone"):
                        sink_event = await self.discord_sink.adispatch(
                            audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, live_sent
                        )
                        if self.audio_sink_router is not None:
                            self.audio_sink_router(
                                audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, live_sent
                            )
                        self.routed_audio_events.append({
                            "mode": audio_out_mode,
                            "bot": sink_event["bot"],
                            "node_id": node_id,
                            "chunk_index": live_streamed_count,
                            "pcm_bytes": len(raw_pcm),
                            "sample_rate": self.mock_sample_rate,
                        })
                    yield build_sse_event(
                        "sentence",
                        {
                            "text": live_sent,
                            "sentence_index": live_streamed_count,
                            "engine": active_tts_engine,
                            "voice_name": active_voice_name,
                            "format": "pcm",
                            "sample_rate": self.mock_sample_rate,
                            "channels": 1,
                            "is_final": False,
                            "audio_out_mode": audio_out_mode,
                            "audio_b64": b64_pcm,
                        },
                    )
                    live_streamed_count += 1

                if handler_task.done():
                    break

                elapsed_s = time.monotonic() - brain_start
                if (
                    self.llm_config.filler_delay_ms > 0
                    and not filler_1_sent
                    and elapsed_s >= filler_1_s
                ):
                    filler_1_sent = True
                    filler_pcm = self._synthesize_sentence_pcm("One moment.", is_filler=True)
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
                    filler_pcm_2 = self._synthesize_sentence_pcm("Still working on that.", is_filler=True)
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
                if (
                    self.llm_config.async_handoff_ms > 0
                    and elapsed_s >= handoff_s
                ):
                    handoff_text = "Still pulling those details. I will drop the full breakdown in Discord."
                    handoff_pcm = self._synthesize_sentence_pcm(handoff_text, is_filler=True)
                    if first_audio_ms is None:
                        first_audio_ms = int((time.monotonic() - t_start) * 1000)
                    yield build_sse_event("state", {"state": "speaking"})
                    yield build_sse_event(
                        "sentence",
                        {
                            "text": handoff_text,
                            "filler": True,
                            "async_handoff": True,
                            "engine": self.llm_config.tts_engine or "kokoro",
                            "format": "pcm",
                            "sample_rate": self.mock_sample_rate,
                            "channels": 1,
                            "is_final": True,
                            "audio_out_mode": audio_out_mode,
                            "audio_b64": base64.b64encode(handoff_pcm).decode("ascii"),
                        },
                    )
                    handoff_ms = int((time.monotonic() - t_start) * 1000)
                    yield build_sse_event(
                        "done",
                        {
                            "duration_ms": handoff_ms,
                            "async_handoff": True,
                            "first_audio_ms": first_audio_ms,
                            "total_ms": handoff_ms,
                        },
                    )

                    async def _supervise_detached_turn() -> None:
                        try:
                            bg_res = await handler_task
                            bg_total_ms = int((time.monotonic() - t_start) * 1000)
                            bg_entry = {
                                "node_id": node_id,
                                "session_id": session_id,
                                "mode": "async_handoff",
                                "audio_out_mode": audio_out_mode,
                                "transcript": bg_res.get("transcript", parsed_turn.get("prompt") or ""),
                                "reply": bg_res.get("reply", ""),
                                "voice_name": self.llm_config.voice_name or DEFAULT_VOICE_NAME,
                                "tts_engine": self.llm_config.tts_engine or "kokoro",
                                "has_image": bool(parsed_turn.get("image_bytes")),
                                "burst_count": len(parsed_turn.get("burst_images") or []),
                                "stt_ms": int(bg_res.get("stt_ms", 0)),
                                "first_text_ms": bg_total_ms,
                                "first_audio_ms": first_audio_ms,
                                "total_ms": bg_total_ms,
                            }
                            rec = await self.turn_log_sink.adispatch(bg_entry)
                            self.turn_logs.append(rec)
                            if self.turn_log_router is not None:
                                cb_res = self.turn_log_router(rec)
                                if inspect.isawaitable(cb_res):
                                    await cb_res
                        except Exception as exc:
                            logger.error("Detached async handoff task failed for node_id=%s: %s", node_id, exc)
                            err_entry = {
                                "node_id": node_id,
                                "session_id": session_id,
                                "mode": "error",
                                "audio_out_mode": audio_out_mode,
                                "transcript": parsed_turn.get("prompt") or "voice turn",
                                "reply": "",
                                "error": str(exc),
                                "voice_name": self.llm_config.voice_name or DEFAULT_VOICE_NAME,
                                "tts_engine": self.llm_config.tts_engine or "kokoro",
                                "has_image": bool(parsed_turn.get("image_bytes")),
                                "burst_count": len(parsed_turn.get("burst_images") or []),
                                "stt_ms": 0,
                                "first_text_ms": -1,
                                "first_audio_ms": first_audio_ms or -1,
                                "total_ms": int((time.monotonic() - t_start) * 1000),
                            }
                            rec = await self.turn_log_sink.adispatch(err_entry)
                            self.turn_logs.append(rec)
                            if self.turn_log_router is not None:
                                cb_res = self.turn_log_router(rec)
                                if inspect.isawaitable(cb_res):
                                    await cb_res

                    asyncio.create_task(_supervise_detached_turn())
                    return
                try:
                    await asyncio.wait_for(asyncio.shield(handler_task), timeout=0.02)
                except asyncio.TimeoutError:
                    continue

            result = await handler_task
            # Drain any final sentences queued just before handler_task returned
            while not live_sentence_queue.empty():
                live_sent = live_sentence_queue.get_nowait()
                live_streamed_sentences.append(live_sent)
                raw_pcm = await loop.run_in_executor(
                    None, self._synthesize_sentence_pcm, live_sent
                )
                if first_audio_ms is None:
                    first_audio_ms = int((time.monotonic() - t_start) * 1000)
                if not speaking_state_emitted:
                    speaking_state_emitted = True
                    yield build_sse_event("state", {"state": "speaking"})
                b64_pcm = base64.b64encode(raw_pcm).decode("ascii")
                if audio_out_mode in ("discord_voice", "ble_phone"):
                    sink_event = await self.discord_sink.adispatch(
                        audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, live_sent
                    )
                    if self.audio_sink_router is not None:
                        self.audio_sink_router(
                            audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, live_sent
                        )
                    self.routed_audio_events.append({
                        "mode": audio_out_mode,
                        "bot": sink_event["bot"],
                        "node_id": node_id,
                        "chunk_index": live_streamed_count,
                        "pcm_bytes": len(raw_pcm),
                        "sample_rate": self.mock_sample_rate,
                    })
                yield build_sse_event(
                    "sentence",
                    {
                        "text": live_sent,
                        "sentence_index": live_streamed_count,
                        "engine": active_tts_engine,
                        "voice_name": active_voice_name,
                        "format": "pcm",
                        "sample_rate": self.mock_sample_rate,
                        "channels": 1,
                        "is_final": False,
                        "audio_out_mode": audio_out_mode,
                        "audio_b64": b64_pcm,
                    },
                )
                live_streamed_count += 1

            stt_ms = int(result.get("stt_ms", (time.monotonic() - t_start) * 1000))
            transcript_text = result.get("transcript", parsed_turn.get("prompt") or "")

            is_ghost, ghost_reason = is_stt_ghost(
                transcript_text=transcript_text,
                audio_bytes=parsed_turn.get("audio_bytes"),
                min_voiced_ms=self.llm_config.min_voiced_ms,
                has_explicit_prompt=has_prompt,
                has_images=has_images,
                use_silero_vad=self.llm_config.use_silero_vad,
                vad_gate=self.vad_gate,
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
            all_result_sentences = result.get("sentences")
            if live_streamed_sentences and all_result_sentences:
                # Filter out sentences that were already synthesized and yielded live during `_on_sentence`
                remaining: List[str] = []
                already = list(live_streamed_sentences)
                for s in all_result_sentences:
                    if already and s.strip() == already[0].strip():
                        already.pop(0)
                    else:
                        remaining.append(s)
                streamed_sentences = remaining
            elif live_streamed_sentences and not all_result_sentences:
                all_split = split_into_sentences(reply_text)
                remaining = []
                already = list(live_streamed_sentences)
                for s in all_split:
                    if already and s.strip() == already[0].strip():
                        already.pop(0)
                    else:
                        remaining.append(s)
                streamed_sentences = remaining
            else:
                streamed_sentences = all_result_sentences

        # Apply optional spoken reply word cap (default 0 = uncapped)
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

        if streamed_sentences is not None and self.llm_config.reply_cap_words <= 0:
            sentences = list(streamed_sentences)
        else:
            sentences = split_into_sentences(reply_text)
        loop = asyncio.get_running_loop()

        # Lookahead async pipeline (Mirrormere streaming pattern):
        # Start synthesizing sentence i+1 in the background executor BEFORE yielding
        # sentence i over SSE, so Sentence 0 streams immediately upon synthesis and
        # subsequent sentences render concurrently behind active ESP32 playback.
        total_sentences = len(sentences) if explicit_pcm_chunks is None else len(explicit_pcm_chunks)
        lookahead_task: Optional[asyncio.Future[bytes]] = None
        if explicit_pcm_chunks is None and total_sentences > 0:
            lookahead_task = loop.run_in_executor(None, self._synthesize_sentence_pcm, sentences[0])

        for idx in range(total_sentences):
            sent_text = sentences[idx] if idx < len(sentences) else ""
            if explicit_pcm_chunks is not None:
                raw_pcm = explicit_pcm_chunks[idx]
            else:
                assert lookahead_task is not None
                next_task: Optional[asyncio.Future[bytes]] = None
                if idx + 1 < total_sentences:
                    next_task = loop.run_in_executor(
                        None, self._synthesize_sentence_pcm, sentences[idx + 1]
                    )
                raw_pcm = await lookahead_task
                lookahead_task = next_task

            is_final = (idx == total_sentences - 1)
            out_sentence_idx = live_streamed_count + idx
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
                    "chunk_index": out_sentence_idx,
                    "pcm_bytes": len(raw_pcm),
                    "sample_rate": self.mock_sample_rate,
                })
            if self.event_format == "sentence":
                yield build_sse_event(
                    "sentence",
                    {
                        "text": sent_text,
                        "sentence_index": out_sentence_idx,
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
        turn_log_entry = {
            "node_id": node_id,
            "session_id": session_id,
            "mode": parsed_turn.get("mode", "interact"),
            "audio_out_mode": audio_out_mode,
            "transcript": transcript_text,
            "reply": reply_text,
            "voice_name": active_voice_name,
            "tts_engine": active_tts_engine,
            "has_image": bool(parsed_turn.get("image_bytes")),
            "burst_count": len(parsed_turn.get("burst_images") or []),
            "stt_ms": stt_ms,
            "first_text_ms": first_text_ms,
            "first_audio_ms": first_audio_ms,
            "total_ms": total_ms,
        }
        logged_record = await self.turn_log_sink.adispatch(turn_log_entry)
        self.turn_logs.append(logged_record)
        if self.turn_log_router is not None:
            res_cb = self.turn_log_router(logged_record)
            if inspect.isawaitable(res_cb):
                await res_cb
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

    @app.get("/api/voice/logs")
    def get_voice_turn_logs(request: Request, limit: int = 50):
        if srv.auth_required or srv.verifier.device_tokens:
            headers = dict(request.headers)
            client_ip = request.client.host if request.client else "0.0.0.0"
            ok, code, err = srv.verifier.verify(headers, client_ip=client_ip)
            if not ok:
                admin_ok, _, _ = srv.verify_admin_auth(headers)
                if not admin_ok:
                    return JSONResponse(status_code=code, content=err)
        bounded = max(1, min(int(limit or 50), 200))
        return {
            "ok": True,
            "count": len(srv.turn_logs[-bounded:]),
            "logs": list(srv.turn_logs[-bounded:]),
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
                location=parsed_turn.get("location"),
            )
            if not j_res.get("ghost_filtered"):
                j_log = await srv.turn_log_sink.adispatch({
                    "node_id": parsed_turn["node_id"],
                    "session_id": parsed_turn["session_id"],
                    "mode": "journal",
                    "audio_out_mode": parsed_turn.get("audio_out_mode", "speaker"),
                    "transcript": j_res.get("transcript", ""),
                    "reply": "",
                    "voice_name": srv.llm_config.voice_name or DEFAULT_VOICE_NAME,
                    "tts_engine": srv.llm_config.tts_engine or "kokoro",
                    "has_image": bool(parsed_turn.get("image_bytes")),
                    "burst_count": len(parsed_turn.get("burst_images") or []),
                    "stt_ms": 0,
                    "first_text_ms": 0,
                    "first_audio_ms": 0,
                    "total_ms": 0,
                })
                srv.turn_logs.append(j_log)
                if srv.turn_log_router is not None:
                    res_cb = srv.turn_log_router(j_log)
                    if inspect.isawaitable(res_cb):
                        await res_cb

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
