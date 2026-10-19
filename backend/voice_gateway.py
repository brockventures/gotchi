#!/usr/bin/env python3
"""
GOTCHI V1 — Reference Voice Gateway Server (`POST /api/voice/interact`)
======================================================================
Satisfies:
- F15: Hub wire contract handling per-unit `voice_url` targeting Zero gateway or Mirrormere.
- F17: Cold-start hotspot turn completion test harness.
- F14 & F20: Multimodal single JPEG snapshot (`image`) and 5-frame burst (`image_0`..`image_4`).
- T3.2: Per-device `BearerTokenVerifier` auth integration.
- SSE Streaming Event Protocol: supports both live `sentence` (`audio_b64`) and `audio_chunk`
  (`data`) events, plus pluggable `turn_handler` for live STT/Vision/TTS integration.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Mapping, Optional

try:
    from fastapi import FastAPI, Header, Request
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:
    FastAPI = None

from backend.gateway_auth import BearerTokenVerifier

logger = logging.getLogger("gotchi_gateway")


def generate_synthetic_pcm(duration_s: float = 0.5, sample_rate: int = 24000) -> bytes:
    """Generate 16-bit mono PCM audio for reference TTS playback."""
    num_samples = int(duration_s * sample_rate)
    return b"\x00\x00" * num_samples


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


class VoiceGatewayService:
    """Core domain logic for parsing GOTCHI multipart turns and generating SSE events."""

    VALID_AUDIO_OUT_MODES = ("speaker", "discord_voice", "ble_phone")

    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        auth_required: bool = False,
        default_reply_text: str = "Gotchi voice response verified.",
        mock_sample_rate: int = 24000,
        event_format: str = "sentence",
        turn_handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        audio_sink_router: Optional[Callable[[str, str, bytes, int, str], None]] = None,
    ):
        self.verifier = verifier or BearerTokenVerifier.from_env_or_file()
        self.auth_required = auth_required or bool(self.verifier.device_tokens)
        self.default_reply_text = default_reply_text
        self.mock_sample_rate = mock_sample_rate
        self.event_format = event_format
        self.turn_handler = turn_handler
        self.audio_sink_router = audio_sink_router
        self.routed_audio_events: List[Dict[str, Any]] = []
        self.interactions_count = 0

    def parse_multipart_data(
        self,
        form_data: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract audio, images (single or burst), node_id, session_id, prompt, audio_out_mode.
        Rejects empty (`0-byte`) uploaded files and invalid `audio_out_mode` values.
        """
        node_id = form_data.get("node_id") or "gotchi-device"
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

        return {
            "node_id": str(node_id),
            "session_id": str(session_id),
            "prompt": str(prompt) if prompt is not None else None,
            "audio_out_mode": str(audio_out_mode),
            "audio_bytes": audio_bytes,
            "image_bytes": image_bytes,
            "burst_images": burst_images,
        }

    async def generate_sse_stream(
        self,
        parsed_turn: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Generate SSE event stream matching docs/MIRRORMERE_VOICE_CLIENT.md."""
        self.interactions_count += 1
        t_start = time.monotonic()

        yield build_sse_event("turn", {"turn_id": parsed_turn["session_id"]})
        yield build_sse_event("state", {"state": "transcribing"})
        await asyncio.sleep(0.005)

        if self.turn_handler is not None:
            result = self.turn_handler(parsed_turn)
            transcript_text = result.get("transcript", "")
            reply_text = result.get("reply", self.default_reply_text)
            pcm_chunks = result.get("pcm_chunks") or [
                generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate)
            ]
        else:
            if parsed_turn.get("audio_bytes") and parsed_turn.get("prompt"):
                transcript_text = parsed_turn["prompt"]
            elif parsed_turn.get("audio_bytes"):
                transcript_text = "What is the status?"
            elif parsed_turn.get("prompt"):
                transcript_text = parsed_turn["prompt"]
            elif parsed_turn.get("burst_images"):
                transcript_text = "Analyzing 5-frame burst capture"
            else:
                transcript_text = "Analyzing camera snapshot"

            if parsed_turn.get("burst_images"):
                reply_text = f"Received 5-frame burst ({len(parsed_turn['burst_images'])} images). Object tracking confirmed."
            elif parsed_turn.get("image_bytes"):
                reply_text = "Camera snapshot received. Identification verified."
            else:
                reply_text = self.default_reply_text

            pcm_chunks = [
                generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate),
                generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate),
            ]

        yield build_sse_event(
            "transcript",
            {"text": transcript_text, "transcript": transcript_text, "speaker": "ryan"},
        )
        await asyncio.sleep(0.005)

        yield build_sse_event("state", {"state": "thinking"})
        yield build_sse_event("thinking", {"elapsed_seconds": 1})
        await asyncio.sleep(0.005)

        yield build_sse_event("state", {"state": "synthesizing"})
        yield build_sse_event("reply", {"reply": reply_text, "tts_engine": "kokoro"})
        await asyncio.sleep(0.005)

        yield build_sse_event("state", {"state": "speaking"})

        audio_out_mode = parsed_turn.get("audio_out_mode", "speaker")
        node_id = parsed_turn.get("node_id", "gotchi-device")

        for idx, raw_pcm in enumerate(pcm_chunks):
            is_final = (idx == len(pcm_chunks) - 1)
            b64_pcm = base64.b64encode(raw_pcm).decode("ascii")
            if audio_out_mode in ("discord_voice", "ble_phone"):
                if self.audio_sink_router is not None:
                    self.audio_sink_router(audio_out_mode, node_id, raw_pcm, self.mock_sample_rate, reply_text)
                self.routed_audio_events.append({
                    "mode": audio_out_mode,
                    "node_id": node_id,
                    "chunk_index": idx,
                    "pcm_bytes": len(raw_pcm),
                    "sample_rate": self.mock_sample_rate,
                })
            if self.event_format == "sentence":
                yield build_sse_event(
                    "sentence",
                    {
                        "text": reply_text if idx == 0 else "",
                        "engine": "kokoro",
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

        duration_ms = int((time.monotonic() - t_start) * 1000)
        yield build_sse_event("done", {"duration_ms": duration_ms})


def create_app(service: Optional[VoiceGatewayService] = None) -> "FastAPI":
    """Factory to create FastAPI instance with /api/voice/interact endpoint."""
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed")

    app = FastAPI(title="Gotchi Reference Voice Gateway")
    srv = service or VoiceGatewayService()

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "gotchi-voice-gateway"}

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

    return app
