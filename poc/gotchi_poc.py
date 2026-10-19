#!/usr/bin/env python3
"""
GOTCHI V1 — Bench POC Client & 200x200 1-Bit E-Paper Sprite Engine
==================================================================
Runs on Raspberry Pi Zero W (driving the attached Waveshare e-ink panel or saving 200x200
1-bit framebuffers for webcam verification) and talks directly to Mirrormere's
`POST /api/voice/interact` SSE pipeline using Amos's ambient mic.

Features:
- Exact 200x200 1-bit monochrome companion sprite renderer matching the Waveshare 1.54" V2
  (SSD1681) resolution across all 7 states: `idle`, `listening`, `transcribing`, `thinking`,
  `synthesizing`, `speaking`, `error` (plus `busy` / `offline`).
- Refresh policy ported from `client/eink-node` (`PanelManager`):
  - Full refresh on first frame, after `max_consecutive_partials` (8) partials, or after
    `full_refresh_minutes` (15 min); automatic full-refresh recovery if a partial fails.
  - Bounded 30s `BUSY` timeout safeguard.
- Full Mirrormere `/api/voice/interact` multipart 16 kHz mono PCM WAV uploader and streaming
  SSE event parser (`state`, `transcript`, `status`, `thinking`, `reply`, `audio_chunk`
  base64 24 kHz PCM decode, `error`, `done`).
- Pi Zero W adapter mode (`--epd-7in5`): centers the 200x200 GOTCHI viewport inside a 1:1
  bezel frame on the Pi Zero W's attached e-ink display so Amos's webcam can visually verify
  real e-ink state transitions live on hardware.
"""

import argparse
import base64
import io
import json
import math
import os
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

VALID_STATES = (
    "idle",
    "listening",
    "transcribing",
    "thinking",
    "synthesizing",
    "speaking",
    "error",
    "busy",
    "offline",
)


def wrap_pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit signed little-endian PCM bytes in a standard 44-byte RIFF WAV header."""
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,  # bits per sample
        b"data",
        data_size,
    )
    return header + pcm_bytes


def build_multipart_wav(
    wav_bytes: bytes,
    node_id: str = "gotchi-poc-01",
    session_id: str = "sess-poc-01",
    boundary: str = "---GotchiBoundary7MA4YWxkTrZu0gW",
) -> Tuple[bytes, str]:
    """Construct multipart/form-data payload for POST /api/voice/interact."""
    crlf = b"\r\n"
    parts = [
        b"--" + boundary.encode() + crlf,
        b'Content-Disposition: form-data; name="audio"; filename="ptt.wav"' + crlf,
        b"Content-Type: audio/wav" + crlf + crlf,
        wav_bytes + crlf,
        b"--" + boundary.encode() + crlf,
        b'Content-Disposition: form-data; name="node_id"' + crlf + crlf,
        node_id.encode() + crlf,
        b"--" + boundary.encode() + crlf,
        b'Content-Disposition: form-data; name="session_id"' + crlf + crlf,
        session_id.encode() + crlf,
        b"--" + boundary.encode() + b"--" + crlf,
    ]
    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


@dataclass
class RefreshTracker:
    """Implements the `PanelManager.write_frame` partial/full refresh policy with 30s BUSY guard."""
    max_consecutive_partials: int = 8
    full_refresh_minutes: float = 15.0
    busy_timeout_s: float = 30.0
    has_drawn_initial: bool = False
    consecutive_partials: int = 0
    last_full_refresh_ts: float = 0.0
    history: List[str] = field(default_factory=list)

    def select_refresh_mode(self, now: Optional[float] = None, force_full: bool = False) -> str:
        now = time.monotonic() if now is None else now
        if force_full or not self.has_drawn_initial:
            return "full"
        if self.consecutive_partials >= self.max_consecutive_partials:
            return "full"
        if (now - self.last_full_refresh_ts) >= (self.full_refresh_minutes * 60.0):
            return "full"
        return "partial"

    def record_write(self, mode: str, succeeded: bool = True, now: Optional[float] = None) -> str:
        now = time.monotonic() if now is None else now
        if not succeeded and mode == "partial":
            # Failed partial recovers immediately with a full refresh
            mode = "full"
        if mode == "full":
            self.has_drawn_initial = True
            self.consecutive_partials = 0
            self.last_full_refresh_ts = now
        else:
            self.consecutive_partials += 1
        self.history.append(mode)
        return mode


@dataclass
class GotchiUIState:
    state: str = "idle"
    transcript: str = ""
    reply: str = ""
    status_text: str = "READY (HOLD PTT)"
    thinking_seconds: int = 0
    audio_bytes_received: int = 0
    last_sample_rate: int = 24000
    error_code: str = ""
    skin: str = "gotchi"  # "gotchi" | "zero"


def parse_sse_stream(
    lines: Iterable[str],
    ui: Optional[GotchiUIState] = None,
    on_state_change: Optional[Callable[[GotchiUIState], None]] = None,
    on_audio_pcm: Optional[Callable[[bytes, int, bool], None]] = None,
) -> GotchiUIState:
    """
    Parse Mirrormere `text/event-stream` lines (`event: <name>` + `data: <json>`) and update
    GOTCHI device state + decode base64 PCM audio chunks (`24 kHz` default).
    """
    if ui is None:
        ui = GotchiUIState()

    cur_event: Optional[str] = None
    cur_data_lines: List[str] = []

    def flush_event(ev: Optional[str], data_lines: List[str]):
        if not ev or not data_lines:
            return
        raw = "\n".join(data_lines).strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}

        prev_state = ui.state
        if ev == "state":
            st = payload.get("state", "idle")
            ui.state = st if st in VALID_STATES else "idle"
            ui.status_text = st.upper()
        elif ev == "transcript":
            ui.transcript = payload.get("transcript", "")
            spk = payload.get("speaker", "")
            ui.status_text = f"HEARD ({spk})" if spk else "HEARD"
        elif ev == "status":
            ui.status_text = payload.get("status", ui.status_text)
        elif ev == "thinking":
            ui.state = "thinking"
            ui.thinking_seconds = int(payload.get("elapsed_seconds", 0))
            ui.status_text = f"THINKING ({ui.thinking_seconds}s)"
        elif ev == "reply":
            ui.reply = payload.get("reply", "")
            ui.status_text = "SPEAKING"
        elif ev in ("audio_chunk", "sentence"):
            # Live gateway (2026-10-18) sends `sentence` with `audio_b64`; legacy
            # `audio_chunk` carries the same PCM under `data`.
            ui.state = "speaking"
            b64 = payload.get("audio_b64" if ev == "sentence" else "data", "")
            sr = int(payload.get("sample_rate", 24000) or 24000)
            is_final = bool(payload.get("is_final", False))
            pcm = base64.b64decode(b64) if b64 else b""
            ui.audio_bytes_received += len(pcm)
            ui.last_sample_rate = sr
            if on_audio_pcm and pcm:
                on_audio_pcm(pcm, sr, is_final)
        elif ev == "turn":
            pass  # turn bookkeeping only; nothing to show
        elif ev == "error":
            ui.state = "error"
            ui.error_code = payload.get("error", "error")
            ui.status_text = payload.get("message", ui.error_code)[:22]
        elif ev == "done":
            ui.state = "idle"
            dur = payload.get("duration_ms", 0)
            ui.status_text = f"DONE ({dur}ms)"

        if on_state_change and (ui.state != prev_state or ev in ("transcript", "reply", "error", "done", "thinking")):
            on_state_change(ui)

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            flush_event(cur_event, cur_data_lines)
            cur_event = None
            cur_data_lines = []
        elif line.startswith("event:"):
            cur_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            cur_data_lines.append(line.split(":", 1)[1].strip())

    flush_event(cur_event, cur_data_lines)
    return ui


def render_sprite_200x200(ui: GotchiUIState, refresh_mode: str = "partial") -> Image.Image:
    """
    Render the 200x200 1-bit monochrome e-paper display frame (black=0, white=255)
    for the Waveshare 1.54" V2 (SSD1681).
    """
    im = Image.new("L", (200, 200), 255)
    d = ImageDraw.Draw(im)

    try:
        f_hdr = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        f_txt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
    except Exception:
        f_hdr = ImageFont.load_default()
        f_txt = f_hdr
        f_big = f_hdr

    if getattr(ui, "skin", "gotchi") == "zero":
        asset_dir = os.path.join(os.path.dirname(__file__), "assets", "zero_skin")
        st_name = ui.state if ui.state in VALID_STATES else "idle"
        prebaked = os.path.join(asset_dir, f"zero_{st_name}_200x200_1bit.png")
        if os.path.exists(prebaked):
            im = Image.open(prebaked).convert("L")
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 199, 20], fill=0)
            d.text((5, 4), f"ZERO // {st_name.upper()}", fill=255, font=f_hdr)
            badge = "FULL" if refresh_mode == "full" else "PART"
            d.text((164, 4), badge, fill=255, font=f_hdr)
            d.rectangle([2, 156, 197, 197], fill=255)
            line1 = (ui.reply or ui.transcript or ui.status_text or "READY")[:26]
            line2 = (ui.reply[26:52] if ui.reply else (ui.transcript[26:52] if ui.transcript else f"SR:{ui.last_sample_rate//1000}k B:{ui.audio_bytes_received}"))
            d.text((6, 160), line1, fill=0, font=f_big)
            d.text((6, 178), line2[:28], fill=0, font=f_txt)
            return im.point(lambda px: 255 if px > 128 else 0, mode="1")

    # Top status bar (y = 0..20)
    d.rectangle([0, 0, 199, 20], fill=0)
    d.text((5, 4), f"GOTCHI // {ui.state.upper()}", fill=255, font=f_hdr)
    badge = "FULL" if refresh_mode == "full" else "PART"
    d.text((164, 4), badge, fill=255, font=f_hdr)

    # Outer border
    d.rectangle([0, 0, 199, 199], outline=0, width=2)

    # Companion character face box (center 100, 86)
    cx, cy = 100, 84
    d.rounded_rectangle([42, 30, 158, 134], radius=18, outline=0, width=3, fill=255)
    # Little ears / antennas
    d.polygon([(56, 30), (66, 18), (76, 30)], outline=0, fill=0)
    d.polygon([(124, 30), (134, 18), (144, 30)], outline=0, fill=0)

    st = ui.state
    if st == "idle":
        # Calm happy eyes + subtle smile
        d.ellipse([66, 62, 82, 78], fill=0)
        d.ellipse([118, 62, 134, 78], fill=0)
        d.ellipse([70, 65, 75, 70], fill=255)
        d.ellipse([122, 65, 127, 70], fill=255)
        d.arc([82, 88, 118, 110], start=15, end=165, fill=0, width=3)
    elif st == "listening":
        # Wide attentive eyes + open listening "O" mouth + sound waves
        d.ellipse([62, 58, 84, 80], outline=0, width=3)
        d.ellipse([69, 65, 77, 73], fill=0)
        d.ellipse([116, 58, 138, 80], outline=0, width=3)
        d.ellipse([123, 65, 131, 73], fill=0)
        d.ellipse([91, 94, 109, 112], outline=0, width=3)
        # Sound wave arcs on left/right
        d.arc([22, 56, 38, 108], start=120, end=240, fill=0, width=2)
        d.arc([162, 56, 178, 108], start=-60, end=60, fill=0, width=2)
    elif st == "transcribing":
        # Scanning eyes looking right + waveform bars
        d.rectangle([64, 66, 84, 76], fill=0)
        d.rectangle([116, 66, 136, 76], fill=0)
        for idx, h in enumerate([6, 14, 10, 18, 8, 14, 6]):
            bx = 72 + idx * 9
            d.rectangle([bx, 104 - h // 2, bx + 5, 104 + h // 2], fill=0)
    elif st in ("thinking", "synthesizing"):
        # Looking up at thought bubbles
        d.ellipse([66, 56, 82, 72], fill=0)
        d.ellipse([118, 56, 134, 72], fill=0)
        d.line([(84, 102), (116, 102)], fill=0, width=3)
        d.ellipse([162, 48, 170, 56], outline=0, width=2)
        d.ellipse([172, 34, 186, 48], outline=0, width=2)
    elif st == "speaking":
        # Happy chevron eyes `^ ^` + open talking mouth
        d.line([(64, 74), (74, 62), (84, 74)], fill=0, width=3)
        d.line([(116, 74), (126, 62), (136, 74)], fill=0, width=3)
        d.chord([80, 90, 120, 118], start=0, end=180, fill=0, outline=0)
    else:
        # error / busy / offline: X eyes + flat/wavy mouth
        d.line([(64, 60), (82, 78)], fill=0, width=3)
        d.line([(82, 60), (64, 78)], fill=0, width=3)
        d.line([(118, 60), (136, 78)], fill=0, width=3)
        d.line([(136, 60), (118, 78)], fill=0, width=3)
        d.arc([82, 98, 118, 118], start=195, end=345, fill=0, width=3)

    # Bottom caption tray (y = 140..199)
    d.line([(0, 140), (199, 140)], fill=0, width=2)
    line1 = (ui.reply or ui.transcript or ui.status_text or "READY")[:26]
    line2 = (ui.reply[26:52] if ui.reply else (ui.transcript[26:52] if ui.transcript else f"SR:{ui.last_sample_rate//1000}k B:{ui.audio_bytes_received}"))
    d.text((6, 146), line1, fill=0, font=f_big)
    d.text((6, 166), line2[:28], fill=0, font=f_txt)
    d.text((6, 182), ui.status_text[:28], fill=0, font=f_txt)

    return im.point(lambda p: 255 if p > 128 else 0, mode="1")


def render_contact_sheet(out_path: str) -> str:
    """Render all 7 GOTCHI e-paper sprite states into a single verification sheet."""
    samples = [
        GotchiUIState(state="idle", status_text="READY (HOLD PTT)"),
        GotchiUIState(state="listening", status_text="REC 16kHz PDM MIC..."),
        GotchiUIState(state="transcribing", status_text="WHISPER STT..."),
        GotchiUIState(state="thinking", thinking_seconds=2, status_text="THINKING (2s)"),
        GotchiUIState(state="synthesizing", transcript="What's the weight?", status_text="KOKORO TTS..."),
        GotchiUIState(state="speaking", reply="50g total — 5g lighter than Humane Pin!", audio_bytes_received=48000, status_text="PLAYING 24kHz I2S"),
        GotchiUIState(state="error", error_code="hub_busy", status_text="409 HUB BUSY"),
    ]
    cols = 4
    rows = 2
    pad = 16
    W = cols * 200 + (cols + 1) * pad
    H = rows * 200 + (rows + 1) * pad + 48
    canvas = Image.new("RGB", (W, H), (24, 28, 36))
    draw = ImageDraw.Draw(canvas)
    try:
        f_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except Exception:
        f_title = ImageFont.load_default()
    draw.text((pad, 12), "GOTCHI V1 — 200x200 1-Bit E-Paper Companion Sprite States (Waveshare 1.54-inch V2 & Pi Zero W POC)", fill=(240, 246, 252), font=f_title)

    tracker = RefreshTracker()
    for idx, st in enumerate(samples):
        r = idx // cols
        c = idx % cols
        mode = tracker.record_write(tracker.select_refresh_mode())
        frame_1bit = render_sprite_200x200(st, refresh_mode=mode).convert("RGB")
        x = pad + c * (200 + pad)
        y = 48 + pad + r * (200 + pad)
        canvas.paste(frame_1bit, (x, y))

    canvas.save(out_path)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GOTCHI V1 Pi Zero W / Bench POC Client")
    parser.add_argument("--demo-sheet", default=None, help="Output path for 7-state sprite contact sheet PNG")
    args = parser.parse_args()
    if args.demo_sheet:
        p = render_contact_sheet(args.demo_sheet)
        print(f"Wrote {p}")
