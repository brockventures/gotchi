#!/usr/bin/env python3
"""
GOTCHI V1 — Reference Voice Gateway Server (`POST /api/voice/interact`)
======================================================================
Satisfies:
- F15: Hub wire contract handling per-unit `voice_url` targeting Zero gateway or Mirrormere.
- F17: Cold-start hotspot turn completion test harness.
- F14 & F20: Multimodal single JPEG snapshot (`image`) and 5-frame burst (`image_0`..`image_4`).
- T3.2: Per-device `BearerTokenVerifier` auth integration.
- SSE Streaming Event Protocol: `state`, `transcript`, `status`, `thinking`, `reply`,
  `audio_chunk` (24 kHz base64 PCM), `error`, `done`.
"""

import asyncio
import base64
import json
import logging
import os
import struct
import time
from typing import AsyncGenerator, Dict, List, Mapping, Optional, Tuple, Union

try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response, status
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:
    FastAPI = None

from backend.gateway_auth import BearerTokenVerifier, extract_bearer_token

logger = logging.getLogger("gotchi_gateway")


def generate_synthetic_pcm(duration_s: float = 0.5, sample_rate: int = 24000) -> bytes:
    """Generate dummy 16-bit mono PCM audio (silence or low tone) for synthetic TTS playback."""
    num_samples = int(duration_s * sample_rate)
    return b"\x00\x00" * num_samples


def build_sse_event(event: str, data: dict) -> str:
    """Format single SSE message with event type and JSON payload."""
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


class VoiceGatewayService:
    """Core domain logic for parsing GOTCHI multipart turns and generating SSE events."""

    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        auth_required: bool = False,
        default_reply_text: str = "Gotchi voice response verified.",
        mock_sample_rate: int = 24000,
    ):
        self.verifier = verifier or BearerTokenVerifier()
        self.auth_required = auth_required
        self.default_reply_text = default_reply_text
        self.mock_sample_rate = mock_sample_rate
        self.interactions_count = 0

    def parse_multipart_data(
        self,
        form_data: Mapping[str, Union[str, bytes, any]],
    ) -> Dict[str, any]:
        """
        Extract audio, images (single or burst), node_id, session_id, prompt, audio_out_mode.
        """
        node_id = form_data.get("node_id") or "gotchi-device"
        session_id = form_data.get("session_id") or f"sess-{int(time.time()*1000)}"
        prompt = form_data.get("prompt")
        audio_out_mode = form_data.get("audio_out_mode") or "speaker"

        audio_bytes = None
        if "audio" in form_data:
            val = form_data["audio"]
            audio_bytes = getattr(val, "file", None) and val.file.read() or val
            if hasattr(audio_bytes, "encode") and isinstance(audio_bytes, str):
                audio_bytes = audio_bytes.encode()

        # Handle single snapshot (`image`)
        image_bytes = None
        if "image" in form_data:
            val = form_data["image"]
            image_bytes = getattr(val, "file", None) and val.file.read() or val
            if hasattr(image_bytes, "encode") and isinstance(image_bytes, str):
                image_bytes = image_bytes.encode()

        # Handle burst snapshots (`image_0` .. `image_4`)
        burst_images: List[bytes] = []
        for i in range(5):
            k = f"image_{i}"
            if k in form_data:
                val = form_data[k]
                b = getattr(val, "file", None) and val.file.read() or val
                if hasattr(b, "encode") and isinstance(b, str):
                    b = b.encode()
                burst_images.append(b)

        # Validation: Must have audio OR image
        if not audio_bytes and not image_bytes and not burst_images:
            raise ValueError("Interaction must contain at least audio or image payload")

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
        parsed_turn: Dict[str, any],
    ) -> AsyncGenerator[str, None]:
        """Generate SSE event stream according to docs/MIRRORMERE_VOICE_CLIENT.md."""
        self.interactions_count += 1
        t_start = time.monotonic()

        # 1. State: transcribing
        yield build_sse_event("state", {"state": "transcribing"})
        await asyncio.sleep(0.01)

        # Determine transcript text
        if parsed_turn.get("audio_bytes"):
            transcript_text = "What is the status?"
        elif parsed_turn.get("prompt"):
            transcript_text = parsed_turn["prompt"]
        elif parsed_turn.get("burst_images"):
            transcript_text = "Analyzing 5-frame burst capture"
        else:
            transcript_text = "Analyzing camera snapshot"

        # 2. Transcript event
        yield build_sse_event("transcript", {"transcript": transcript_text, "speaker": "ryan"})
        await asyncio.sleep(0.01)

        # 3. State: thinking
        yield build_sse_event("state", {"state": "thinking"})
        yield build_sse_event("thinking", {"elapsed_seconds": 1})
        await asyncio.sleep(0.01)

        # 4. State: synthesizing
        yield build_sse_event("state", {"state": "synthesizing"})

        # Customize reply based on modalities present
        if parsed_turn.get("burst_images"):
            reply_text = f"Received 5-frame burst ({len(parsed_turn['burst_images'])} images). Object tracking confirmed."
        elif parsed_turn.get("image_bytes"):
            reply_text = "Camera snapshot received. Identification verified."
        else:
            reply_text = self.default_reply_text

        yield build_sse_event("reply", {"reply": reply_text, "tts_engine": "kokoro"})
        await asyncio.sleep(0.01)

        # 5. Audio chunks (speaking)
        yield build_sse_event("state", {"state": "speaking"})

        # Send 2 audio chunks simulating TTS streaming
        raw_pcm1 = generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate)
        raw_pcm2 = generate_synthetic_pcm(duration_s=0.25, sample_rate=self.mock_sample_rate)

        yield build_sse_event("audio_chunk", {
            "chunk_index": 0,
            "format": "pcm",
            "sample_rate": self.mock_sample_rate,
            "channels": 1,
            "is_final": False,
            "data": base64.b64encode(raw_pcm1).decode("ascii"),
        })
        await asyncio.sleep(0.01)

        yield build_sse_event("audio_chunk", {
            "chunk_index": 1,
            "format": "pcm",
            "sample_rate": self.mock_sample_rate,
            "channels": 1,
            "is_final": True,
            "data": base64.b64encode(raw_pcm2).decode("ascii"),
        })
        await asyncio.sleep(0.01)

        # 6. Done event
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
        # 1. Bearer Token Verification (if configured/required)
        headers = dict(request.headers)
        client_ip = request.client.host if request.client else "0.0.0.0"

        if srv.auth_required or srv.verifier.device_tokens:
            ok, code, err = srv.verifier.verify(headers, client_ip=client_ip)
            if not ok:
                return JSONResponse(status_code=code, content=err)

        # 2. Parse Multipart Payload
        try:
            form = await request.form()
            parsed_turn = srv.parse_multipart_data(form)
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(ve)})
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": "bad_request", "message": f"Multipart parse error: {e}"})

        # 3. Stream SSE Response
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
