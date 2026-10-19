#!/usr/bin/env python3
"""
GOTCHI V1 — Live Gateway Relay Server (`WebSocket /api/live/stream` & `POST /api/live/session`)
==============================================================================================
Satisfies:
- PRD Section 5b (F19, F21): Live bidirectional audio & vision streaming gateway relay.
- Disabled unless explicitly enabled via config (live_mode: false by default).
- Pluggable upstream provider adapter (Gemini Multimodal Live / OpenAI Realtime / Mock provider).
- Supports 16 kHz mono PCM uplink and 24 kHz mono PCM downlink chunks.
- Supports mid-session multimodal frame injection (single JPEG snapshot and 5-photo burst).
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

try:
    from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = None
    WebSocket = None
    WebSocketDisconnect = None

from backend.gateway_auth import BearerTokenVerifier

logger = logging.getLogger("gotchi_live_gateway")


class UpstreamLiveProvider:
    """Pluggable adapter interface for upstream multimodal realtime models."""
    async def connect(self, session_id: str, node_id: str):
        pass

    async def send_audio_chunk(self, pcm_chunk: bytes):
        pass

    async def send_image_frame(self, jpeg_bytes: bytes, frame_index: int = 0):
        pass

    async def receive_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        if False:
            yield {}

    async def close(self):
        pass


class MockLiveProvider(UpstreamLiveProvider):
    """Reference / mock upstream provider for local testing and benchmark turns."""
    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self.session_id: Optional[str] = None
        self.node_id: Optional[str] = None
        self.audio_chunks_received = 0
        self.images_received = 0
        self.is_connected = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, session_id: str, node_id: str):
        self.session_id = session_id
        self.node_id = node_id
        self.is_connected = True
        # Send initial session confirmation
        await self._queue.put({"type": "session_started", "session_id": session_id})

    async def send_audio_chunk(self, pcm_chunk: bytes):
        self.audio_chunks_received += 1
        # Echo synthetic reply audio every 5 audio chunks
        if self.audio_chunks_received % 5 == 0:
            synthetic_pcm = b"\x10\x00" * 480  # 960 bytes (20ms at 24kHz)
            b64_pcm = base64.b64encode(synthetic_pcm).decode()
            await self._queue.put({
                "type": "audio",
                "sample_rate": self.sample_rate,
                "audio_b64": b64_pcm,
            })

    async def send_image_frame(self, jpeg_bytes: bytes, frame_index: int = 0):
        self.images_received += 1
        await self._queue.put({
            "type": "text",
            "text": f"Received frame {frame_index} ({len(jpeg_bytes)} bytes)",
        })

    async def receive_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        while self.is_connected:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

    async def close(self):
        self.is_connected = False


class LiveGatewayService:
    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        provider_factory: Optional[Callable[[], UpstreamLiveProvider]] = None,
        live_mode_enabled: bool = False,
    ):
        self.verifier = verifier or BearerTokenVerifier()
        self.provider_factory = provider_factory or (lambda: MockLiveProvider())
        self.live_mode_enabled = live_mode_enabled  # Disabled by default per F19/F21

    def is_enabled(self) -> bool:
        return self.live_mode_enabled

    def enable(self):
        self.live_mode_enabled = True

    def disable(self):
        self.live_mode_enabled = False


def create_live_app(service: Optional[LiveGatewayService] = None) -> "FastAPI":
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed")

    app = FastAPI(title="Gotchi Go Live Gateway Relay")
    srv = service or LiveGatewayService()

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "gotchi-live-gateway",
            "live_mode_enabled": srv.is_enabled(),
        }

    @app.post("/api/live/session")
    async def create_session(request: Request):
        """Initiate or validate Go Live session authorization and feature toggle."""
        if not srv.is_enabled():
            return JSONResponse(
                status_code=403,
                content={"error": "live_mode_disabled", "message": "Go Live mode is disabled by default"}
            )

        headers = dict(request.headers)
        client_ip = request.client.host if request.client else "0.0.0.0"
        if srv.verifier.device_tokens:
            ok, code, err = srv.verifier.verify(headers, client_ip=client_ip)
            if not ok:
                return JSONResponse(status_code=code, content=err)

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        node_id = body.get("node_id", "gotchi-live-node")
        session_id = f"live-{int(time.time()*1000)}"

        return {
            "ok": True,
            "session_id": session_id,
            "node_id": node_id,
            "sample_rate_uplink": 16000,
            "sample_rate_downlink": 24000,
        }

    @app.websocket("/api/live/ws")
    async def live_websocket(websocket: WebSocket):
        """Bidirectional WebSocket streaming endpoint for PCM audio and JPEG injection."""
        await websocket.accept()

        if not srv.is_enabled():
            await websocket.send_json({
                "type": "error",
                "error": "live_mode_disabled",
                "message": "Go Live is disabled",
            })
            await websocket.close(code=1008)
            return

        provider = srv.provider_factory()
        session_id = f"ws-live-{int(time.time()*1000)}"
        await provider.connect(session_id, "gotchi-ws-node")

        async def downstream_pump():
            try:
                async for event in provider.receive_events():
                    await websocket.send_json(event)
            except Exception as e:
                logger.debug(f"Downstream pump exit: {e}")

        pump_task = asyncio.create_task(downstream_pump())

        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"]:
                    await provider.send_audio_chunk(msg["bytes"])
                elif "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    kind = data.get("type", "")
                    if kind == "image":
                        raw_b64 = data.get("image_b64", "")
                        frame_idx = data.get("frame_index", 0)
                        if raw_b64:
                            img_bytes = base64.b64decode(raw_b64)
                            await provider.send_image_frame(img_bytes, frame_idx)
                    elif kind == "ping":
                        await websocket.send_json({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            await provider.close()

    return app
