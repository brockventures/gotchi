#!/usr/bin/env python3
"""
GOTCHI V1 — Live Gateway Relay Server (`WebSocket /api/live/ws` & `POST /api/live/session`)
===========================================================================================
Satisfies:
- PRD Section 5b (F19, F21): Live bidirectional audio & vision streaming gateway relay.
- Disabled unless explicitly enabled via config (`live_mode: false` by default).
- Enforces Bearer token auth on BOTH `POST /api/live/session` and `WebSocket /api/live/ws`
  whenever `auth_required` is True or `verifier.device_tokens` is populated.
- Resilient to malformed JSON or invalid base64 frames (emits structured `{"type":"error"}`
  without dropping the active WebSocket connection).
- User-customizable upstream provider adapter (`LLMConfig`):
  - `mock` (default): Zero-cost local `MockLiveProvider`.
  - `api_key`: Real WebSocket client (`ApiKeyLiveProvider`) connecting to Gemini Multimodal Live
    (`BidiGenerateContent` with `x-goog-api-key` header) or OpenAI Realtime (`Authorization: Bearer` header).
  - `subscription`: Real CLI subprocess (`claude` / `agy` via `asyncio.create_subprocess_exec`) or
    local/remote subscription proxy (`ws://`, `wss://`, `http://`, `https://`) in `SubscriptionLiveProvider`.
"""

import asyncio
import base64
import binascii
import inspect
import json
import logging
import shlex
import time
import urllib.request
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = None
    WebSocket = None
    WebSocketDisconnect = None

try:
    import websockets
except ImportError:
    websockets = None

from backend.gateway_auth import BearerTokenVerifier
from backend.llm_config import LLMConfig

logger = logging.getLogger("gotchi_live_gateway")


async def _default_ws_connect(uri: str, headers: Dict[str, str]) -> Any:
    """Connects to an upstream WebSocket passing headers via additional_headers or extra_headers."""
    if websockets is None:
        raise RuntimeError("websockets package is required for upstream WebSocket connections")
    sig = inspect.signature(websockets.connect)
    if "additional_headers" in sig.parameters:
        return await websockets.connect(uri, additional_headers=headers)
    return await websockets.connect(uri, extra_headers=headers)


def _default_http_json_post(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous HTTP JSON POST helper executed inside asyncio.to_thread."""
    req_headers = {"Content-Type": "application/json", **headers}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {"type": "ack"}


async def _default_cli_runner(argv: List[str], stdin_payload: bytes) -> bytes:
    """Executes an allowlisted subscription CLI binary (e.g. `claude -p`) with stdin/stdout pipes."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(input=stdin_payload), timeout=30.0)
    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip() or f"exit_code_{proc.returncode}"
        raise RuntimeError(f"Subscription CLI failed: {err_text}")
    return stdout


def parse_upstream_ws_message(raw_msg: Any, default_sample_rate: int = 24000) -> List[Dict[str, Any]]:
    """
    Normalizes Gemini Multimodal Live (`serverContent`), OpenAI Realtime (`response.audio.delta`),
    or generic JSON upstream messages into GOTCHI downlink events.
    """
    if isinstance(raw_msg, (bytes, bytearray)):
        b64_pcm = base64.b64encode(bytes(raw_msg)).decode("ascii")
        return [{"type": "audio", "sample_rate": default_sample_rate, "audio_b64": b64_pcm}]

    if isinstance(raw_msg, str):
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            return [{"type": "text", "text": raw_msg}]
    elif isinstance(raw_msg, dict):
        data = raw_msg
    else:
        return []

    events: List[Dict[str, Any]] = []

    # 1. Gemini Multimodal Live BidiGenerateContent schema
    if "serverContent" in data and isinstance(data["serverContent"], dict):
        sc = data["serverContent"]
        model_turn = sc.get("modelTurn") or {}
        for part in model_turn.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if "text" in part and part["text"]:
                events.append({"type": "text", "text": str(part["text"])})
            inline = part.get("inlineData") or {}
            mime = str(inline.get("mimeType", ""))
            b64_data = inline.get("data")
            if b64_data and ("audio" in mime or not mime):
                events.append({
                    "type": "audio",
                    "sample_rate": default_sample_rate,
                    "audio_b64": str(b64_data),
                })
        return events

    # 2. OpenAI Realtime schema
    msg_type = data.get("type", "")
    if msg_type in ("response.audio.delta", "response.output_audio.delta"):
        delta = data.get("delta", "")
        if delta:
            events.append({
                "type": "audio",
                "sample_rate": default_sample_rate,
                "audio_b64": str(delta),
            })
        return events
    if msg_type in ("response.text.delta", "response.audio_transcript.delta"):
        delta = data.get("delta", "")
        if delta:
            events.append({"type": "text", "text": str(delta)})
        return events

    # 3. Direct / proxy normalized schema
    if msg_type in ("audio", "text", "error", "session_started", "turn_complete"):
        events.append(data)

    return events


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
    """Reference / mock upstream provider for local testing and benchmark turns (zero metered cost)."""
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
        await self._queue.put({
            "type": "session_started",
            "session_id": session_id,
            "auth_mode": "mock",
            "provider": "mock",
        })

    async def send_audio_chunk(self, pcm_chunk: bytes):
        self.audio_chunks_received += 1
        if self.audio_chunks_received % 5 == 0:
            synthetic_pcm = b"\x10\x00" * 480  # 960 bytes (20ms at 24kHz)
            b64_pcm = base64.b64encode(synthetic_pcm).decode("ascii")
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


class ApiKeyLiveProvider(UpstreamLiveProvider):
    """
    Real WebSocket client for Gemini Multimodal Live (`BidiGenerateContent`) and OpenAI Realtime.
    Passes API keys strictly in request headers (`x-goog-api-key` or `Authorization: Bearer`),
    never in URL query parameters.
    """
    GEMINI_WS_BASE = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )
    OPENAI_WS_BASE = "wss://api.openai.com/v1/realtime"

    def __init__(
        self,
        config: LLMConfig,
        sample_rate: int = 24000,
        ws_connector: Optional[Callable[[str, Dict[str, str]], Awaitable[Any]]] = None,
    ):
        self.config = config
        self.sample_rate = sample_rate
        self.ws_connector = ws_connector or _default_ws_connect
        self.session_id: Optional[str] = None
        self.node_id: Optional[str] = None
        self.is_connected = False
        self.audio_chunks_received = 0
        self.images_received = 0
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue()

    def build_upstream_endpoint(self) -> str:
        """Builds the WebSocket URI without embedding secrets in the query string."""
        if self.config.base_url.strip():
            return self.config.base_url.strip()
        if self.config.provider == "openai":
            return f"{self.OPENAI_WS_BASE}?model={self.config.model}"
        return self.GEMINI_WS_BASE

    def build_upstream_headers(self) -> Dict[str, str]:
        """Builds provider-appropriate authentication headers."""
        if self.config.provider == "gemini":
            return {"x-goog-api-key": self.config.api_key}
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

    def build_setup_frame(self) -> Dict[str, Any]:
        if self.config.provider == "openai":
            return {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                },
            }
        model_path = (
            self.config.model
            if self.config.model.startswith("models/")
            else f"models/{self.config.model}"
        )
        return {
            "setup": {
                "model": model_path,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                },
            }
        }

    async def connect(self, session_id: str, node_id: str):
        self.config.validate()
        self.session_id = session_id
        self.node_id = node_id
        uri = self.build_upstream_endpoint()
        headers = self.build_upstream_headers()
        self._ws = await self.ws_connector(uri, headers)
        await self._ws.send(json.dumps(self.build_setup_frame()))
        self.is_connected = True
        self._reader_task = asyncio.create_task(self._read_upstream_loop())
        await self._queue.put({
            "type": "session_started",
            "session_id": session_id,
            "auth_mode": "api_key",
            "provider": self.config.provider,
            "model": self.config.model,
        })

    async def _read_upstream_loop(self):
        try:
            async for raw_msg in self._ws:
                for ev in parse_upstream_ws_message(raw_msg, self.sample_rate):
                    await self._queue.put(ev)
        except Exception as exc:
            if self.is_connected:
                await self._queue.put({
                    "type": "error",
                    "error": "upstream_ws_closed",
                    "message": str(exc),
                })

    async def send_audio_chunk(self, pcm_chunk: bytes):
        if not self.is_connected or self._ws is None:
            raise RuntimeError("ApiKeyLiveProvider is not connected")
        self.audio_chunks_received += 1
        b64 = base64.b64encode(pcm_chunk).decode("ascii")
        if self.config.provider == "openai":
            frame = {"type": "input_audio_buffer.append", "audio": b64}
        else:
            frame = {
                "realtimeInput": {
                    "mediaChunks": [
                        {"mimeType": "audio/pcm;rate=16000", "data": b64}
                    ]
                }
            }
        await self._ws.send(json.dumps(frame))

    async def send_image_frame(self, jpeg_bytes: bytes, frame_index: int = 0):
        if not self.is_connected or self._ws is None:
            raise RuntimeError("ApiKeyLiveProvider is not connected")
        self.images_received += 1
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        if self.config.provider == "openai":
            frame = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{b64}",
                            "frame_index": frame_index,
                        }
                    ],
                },
            }
        else:
            frame = {
                "realtimeInput": {
                    "mediaChunks": [
                        {"mimeType": "image/jpeg", "data": b64}
                    ]
                }
            }
        await self._ws.send(json.dumps(frame))

    async def receive_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        while self.is_connected or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                if not self.is_connected:
                    break
                continue

    async def close(self):
        self.is_connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


class SubscriptionLiveProvider(UpstreamLiveProvider):
    """
    Real subscription-account live adapter supporting:
    1. WebSocket proxy (`ws://` or `wss://` in `subscription_url`) with `Authorization: Bearer <session_token>`.
    2. HTTP proxy (`http://` or `https://` in `subscription_url`) with `Authorization: Bearer <session_token>`.
    3. Allowlisted CLI subprocess bridge (`claude`, `agy`, `gemini`, `codex` in `subscription_command`)
       invoked via `asyncio.create_subprocess_exec`.
    """
    def __init__(
        self,
        config: LLMConfig,
        sample_rate: int = 24000,
        ws_connector: Optional[Callable[[str, Dict[str, str]], Awaitable[Any]]] = None,
        http_poster: Optional[Callable[[str, Dict[str, str], Dict[str, Any]], Dict[str, Any]]] = None,
        cli_runner: Optional[Callable[[List[str], bytes], Awaitable[bytes]]] = None,
    ):
        self.config = config
        self.sample_rate = sample_rate
        self.ws_connector = ws_connector or _default_ws_connect
        self.http_poster = http_poster or _default_http_json_post
        self.cli_runner = cli_runner or _default_cli_runner
        self.session_id: Optional[str] = None
        self.node_id: Optional[str] = None
        self.is_connected = False
        self.audio_chunks_received = 0
        self.images_received = 0
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue()

    def _auth_headers(self) -> Dict[str, str]:
        if self.config.session_token.strip():
            return {"Authorization": f"Bearer {self.config.session_token.strip()}"}
        return {}

    async def connect(self, session_id: str, node_id: str):
        self.config.validate()
        self.session_id = session_id
        self.node_id = node_id
        url = self.config.subscription_url.strip()
        if url.startswith(("ws://", "wss://")):
            self._ws = await self.ws_connector(url, self._auth_headers())
            self._reader_task = asyncio.create_task(self._read_ws_loop())
        elif not url and not self.config.subscription_command.strip():
            raise ValueError(
                "SubscriptionLiveProvider requires subscription_url (ws/http) or subscription_command"
            )
        self.is_connected = True
        await self._queue.put({
            "type": "session_started",
            "session_id": session_id,
            "auth_mode": "subscription",
            "provider": self.config.provider,
            "model": self.config.model,
        })

    async def _read_ws_loop(self):
        try:
            async for raw_msg in self._ws:
                for ev in parse_upstream_ws_message(raw_msg, self.sample_rate):
                    await self._queue.put(ev)
        except Exception as exc:
            if self.is_connected:
                await self._queue.put({
                    "type": "error",
                    "error": "subscription_ws_closed",
                    "message": str(exc),
                })

    async def _dispatch_frame(self, payload: Dict[str, Any]):
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))
            return

        url = self.config.subscription_url.strip()
        if url.startswith(("http://", "https://")):
            if inspect.iscoroutinefunction(self.http_poster):
                resp = await self.http_poster(url, self._auth_headers(), payload)
            else:
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(
                    None, self.http_poster, url, self._auth_headers(), payload
                )
            for ev in parse_upstream_ws_message(resp, self.sample_rate):
                await self._queue.put(ev)
            return

        cmd_str = self.config.subscription_command.strip()
        if cmd_str:
            argv = shlex.split(cmd_str)
            stdin_bytes = json.dumps(payload).encode("utf-8")
            stdout_bytes = await self.cli_runner(argv, stdin_bytes)
            text_out = stdout_bytes.decode("utf-8", errors="replace").strip()
            if text_out:
                for ev in parse_upstream_ws_message(text_out, self.sample_rate):
                    await self._queue.put(ev)
            return

        raise RuntimeError("No active subscription transport (ws, http, or cli)")

    async def send_audio_chunk(self, pcm_chunk: bytes):
        if not self.is_connected:
            raise RuntimeError("SubscriptionLiveProvider is not connected")
        self.audio_chunks_received += 1
        b64 = base64.b64encode(pcm_chunk).decode("ascii")
        await self._dispatch_frame({
            "type": "audio",
            "session_id": self.session_id,
            "node_id": self.node_id,
            "sample_rate": 16000,
            "audio_b64": b64,
        })

    async def send_image_frame(self, jpeg_bytes: bytes, frame_index: int = 0):
        if not self.is_connected:
            raise RuntimeError("SubscriptionLiveProvider is not connected")
        self.images_received += 1
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        await self._dispatch_frame({
            "type": "image",
            "session_id": self.session_id,
            "node_id": self.node_id,
            "frame_index": frame_index,
            "image_b64": b64,
        })

    async def receive_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        while self.is_connected or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                if not self.is_connected:
                    break
                continue

    async def close(self):
        self.is_connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


def create_live_provider(config: LLMConfig) -> UpstreamLiveProvider:
    """Factory selecting Mock, ApiKey, or Subscription provider based on user LLMConfig."""
    config.validate()
    if config.auth_mode == "api_key":
        return ApiKeyLiveProvider(config=config)
    if config.auth_mode == "subscription":
        return SubscriptionLiveProvider(config=config)
    return MockLiveProvider()


class LiveGatewayService:
    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        provider_factory: Optional[Callable[[], UpstreamLiveProvider]] = None,
        live_mode_enabled: bool = False,
        auth_required: bool = False,
        llm_config: Optional[LLMConfig] = None,
    ):
        self.verifier = verifier or BearerTokenVerifier()
        self.llm_config = llm_config or LLMConfig.from_env_or_file()
        self._custom_provider_factory = provider_factory
        self.live_mode_enabled = live_mode_enabled  # Disabled by default per F19/F21
        self.auth_required = bool(auth_required or self.verifier.device_tokens)

    @property
    def provider_factory(self) -> Callable[[], UpstreamLiveProvider]:
        if self._custom_provider_factory is not None:
            return self._custom_provider_factory
        return lambda: create_live_provider(self.llm_config)

    @provider_factory.setter
    def provider_factory(self, fn: Optional[Callable[[], UpstreamLiveProvider]]):
        self._custom_provider_factory = fn

    def is_enabled(self) -> bool:
        return self.live_mode_enabled

    def enable(self):
        self.live_mode_enabled = True

    def disable(self):
        self.live_mode_enabled = False


def register_live_routes(app: "FastAPI", service: Optional[LiveGatewayService] = None) -> LiveGatewayService:
    """Mount `/api/live/session` and `/api/live/ws` onto an existing FastAPI application."""
    srv = service or LiveGatewayService()

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
        if srv.auth_required or srv.verifier.device_tokens:
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
            "llm_config": srv.llm_config.to_public_dict(),
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

        headers = dict(websocket.headers)
        query_token = websocket.query_params.get("token")
        if query_token and "authorization" not in {k.lower() for k in headers}:
            headers["Authorization"] = f"Bearer {query_token}"

        client_ip = websocket.client.host if websocket.client else "0.0.0.0"
        if srv.auth_required or srv.verifier.device_tokens:
            ok, _code, err = srv.verifier.verify(headers, client_ip=client_ip)
            if not ok:
                await websocket.send_json({
                    "type": "error",
                    "error": err.get("error", "unauthorized"),
                    "message": err.get("message", "Unauthorized"),
                })
                await websocket.close(code=1008)
                return

        node_id = headers.get("x-gotchi-node") or headers.get("X-Gotchi-Node") or "gotchi-ws-node"
        provider = srv.provider_factory()
        session_id = f"ws-live-{int(time.time()*1000)}"
        await provider.connect(session_id, node_id)

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
                    try:
                        data = json.loads(msg["text"])
                        if not isinstance(data, dict):
                            raise ValueError("JSON frame must be an object")
                    except (json.JSONDecodeError, ValueError) as exc:
                        await websocket.send_json({
                            "type": "error",
                            "error": "invalid_json",
                            "message": f"Malformed JSON frame: {exc}",
                        })
                        continue

                    kind = data.get("type", "")
                    if kind == "image":
                        raw_b64 = data.get("image_b64", "")
                        frame_idx = data.get("frame_index", 0)
                        if not raw_b64 or not isinstance(raw_b64, str):
                            await websocket.send_json({
                                "type": "error",
                                "error": "missing_image",
                                "message": "image frame missing image_b64 string",
                            })
                            continue
                        try:
                            img_bytes = base64.b64decode(raw_b64, validate=True)
                        except (binascii.Error, ValueError) as exc:
                            await websocket.send_json({
                                "type": "error",
                                "error": "invalid_base64",
                                "message": f"Invalid base64 image payload: {exc}",
                            })
                            continue
                        if len(img_bytes) == 0:
                            await websocket.send_json({
                                "type": "error",
                                "error": "empty_image",
                                "message": "Decoded image payload is 0 bytes",
                            })
                            continue
                        await provider.send_image_frame(img_bytes, int(frame_idx))
                    elif kind == "barge_in":
                        await websocket.send_json({"type": "barge_in_ack"})
                    elif kind == "ping":
                        await websocket.send_json({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            await provider.close()

    return srv


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
            "llm_config": srv.llm_config.to_public_dict(),
        }

    register_live_routes(app, srv)
    return app
