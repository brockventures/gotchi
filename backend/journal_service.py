#!/usr/bin/env python3
"""
GOTCHI V1 — All-Day Journal & Follow-Up Task Distillation Service (`F24` / `T3.5`)
==================================================================================
Provides:
- Passive VAD-gated speech segment ingestion (`POST /api/journal/ingest` or `mode="journal"` on
  `/api/voice/interact` over Wi-Fi or Android BLE relay).
- Whisper ghost & short-clip filtering (`is_stt_ghost`, `min_voiced_ms`).
- Conversation episode stitching (merges adjacent speech segments within `episode_gap_s`).
- Automated follow-up task / action-item extraction (`extract_followup_tasks` + pluggable LLM distiller).
- Daily journal query (`GET /api/journal/entries`), on-demand digest roll-up (`POST /api/journal/summarize`),
  and task state updates (`PATCH /api/journal/tasks/{task_id}`).
"""

from __future__ import annotations

import datetime as dt
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from backend.gateway_auth import BearerTokenVerifier
from backend.voice_gateway import (
    _read_part_bytes,
    is_stt_ghost,
    measure_voiced_audio_ms,
    validate_node_id,
)

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = None  # type: ignore

# Deterministic action-item & follow-up task patterns used when no custom LLM distiller is supplied.
_TASK_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:remind me to|don't forget to|do not forget to)\s+([^.!?\n]+)", re.I), "reminder"),
    (re.compile(r"\b(?:i need to|we need to|need to|have to|must)\s+([^.!?\n]+)", re.I), "todo"),
    (re.compile(r"\b(?:follow up on|follow up with|check on|look into)\s+([^.!?\n]+)", re.I), "followup"),
    (re.compile(r"\b(?:todo|action item|task)\s*[:\-]\s*([^.!?\n]+)", re.I), "task"),
    (re.compile(r"\b(?:i'll send|i will send|i'll email|i will email|let's schedule)\s+([^.!?\n]+)", re.I), "commitment"),
)


def extract_followup_tasks(text: str) -> List[Dict[str, str]]:
    """
    Extracts structured follow-up tasks, reminders, and commitments from a conversation transcript.
    Deduplicates by normalized title while preserving chronological order.
    """
    if not text or not text.strip():
        return []

    seen = set()
    extracted: List[Dict[str, str]] = []
    # Split on sentence boundaries so multi-sentence segments yield clean atomic tasks
    clauses = [c.strip() for c in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if c.strip()]
    for clause in clauses:
        for pattern, category in _TASK_PATTERNS:
            m = pattern.search(clause)
            if m:
                raw_action = m.group(1).strip().rstrip(".,;:-")
                if len(raw_action) < 3:
                    continue
                norm_key = re.sub(r"\s+", " ", raw_action.lower())
                if norm_key not in seen:
                    seen.add(norm_key)
                    title = raw_action[0].upper() + raw_action[1:]
                    extracted.append({
                        "title": title,
                        "category": category,
                        "source_quote": clause,
                    })
                break
    return extracted


class JournalService:
    """
    In-memory + pluggable persistence service for GOTCHI All-Day Journal Mode (`F24`).
    Groups passive voice segments into conversation episodes and extracts follow-up tasks.
    """

    def __init__(
        self,
        verifier: Optional[BearerTokenVerifier] = None,
        auth_required: bool = False,
        min_voiced_ms: int = 400,
        episode_gap_s: float = 300.0,
        stt_transcriber: Optional[Callable[[bytes, Dict[str, Any]], str]] = None,
        llm_distiller: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]] = None,
    ):
        self.verifier = verifier or BearerTokenVerifier.from_env_or_file()
        self.auth_required = auth_required or bool(self.verifier.device_tokens)
        self.min_voiced_ms = min_voiced_ms
        self.episode_gap_s = episode_gap_s
        self.stt_transcriber = stt_transcriber
        self.llm_distiller = llm_distiller

        # Keyed by node_id
        self.segments: Dict[str, List[Dict[str, Any]]] = {}
        self.episodes: Dict[str, List[Dict[str, Any]]] = {}
        self.tasks: Dict[str, List[Dict[str, Any]]] = {}

    def ingest_segment(
        self,
        node_id: str,
        audio_bytes: Optional[bytes] = None,
        transcript: Optional[str] = None,
        session_id: Optional[str] = None,
        timestamp_s: Optional[float] = None,
        transport: str = "wifi",
        location: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Ingests a single VAD-triggered journal segment from GOTCHI, filters ghosts,
        appends to or opens a conversation episode, and extracts follow-up tasks.
        """
        clean_node = validate_node_id(node_id or "gotchi-device")
        now_s = float(timestamp_s if timestamp_s is not None else time.time())
        seg_id = session_id or f"jseg-{int(now_s * 1000)}-{uuid.uuid4().hex[:6]}"

        if audio_bytes is not None and len(audio_bytes) == 0:
            raise ValueError("Uploaded journal 'audio' part is empty (0 bytes)")
        if audio_bytes is None and not (transcript and str(transcript).strip()):
            raise ValueError("Journal segment requires non-empty audio or transcript")

        voiced_ms = measure_voiced_audio_ms(audio_bytes) if audio_bytes else 1000.0
        has_explicit_transcript = bool(transcript and str(transcript).strip())

        if has_explicit_transcript:
            text = str(transcript).strip()
        elif self.stt_transcriber is not None and audio_bytes is not None:
            text = self.stt_transcriber(
                audio_bytes, {"node_id": clean_node, "session_id": seg_id}
            )
        else:
            text = "Noted conversation segment."

        ghost, reason = is_stt_ghost(
            transcript_text=text,
            audio_bytes=audio_bytes,
            min_voiced_ms=self.min_voiced_ms,
            has_explicit_prompt=has_explicit_transcript,
            has_images=False,
        )
        if ghost:
            return {
                "ok": True,
                "node_id": clean_node,
                "segment_id": seg_id,
                "ghost_filtered": True,
                "reason": reason,
                "voiced_ms": round(voiced_ms, 1),
                "tasks_extracted": [],
            }

        iso_ts = dt.datetime.fromtimestamp(now_s, tz=dt.timezone.utc).isoformat()
        segment_entry: Dict[str, Any] = {
            "segment_id": seg_id,
            "node_id": clean_node,
            "timestamp": now_s,
            "iso_timestamp": iso_ts,
            "transport": transport,
            "voiced_ms": round(voiced_ms, 1),
            "transcript": text,
        }
        if location:
            segment_entry["location"] = dict(location)
        node_segments = self.segments.setdefault(clean_node, [])
        node_segments.append(segment_entry)

        # Stitch into active conversation episode if within `episode_gap_s`, else start a new episode
        node_episodes = self.episodes.setdefault(clean_node, [])
        if (
            node_episodes
            and (now_s - float(node_episodes[-1]["end_timestamp"])) <= self.episode_gap_s
        ):
            ep = node_episodes[-1]
            ep["end_timestamp"] = now_s
            ep["segment_ids"].append(seg_id)
            ep["transcripts"].append(text)
            ep["full_text"] = " ".join(ep["transcripts"])
            ep["total_voiced_ms"] = round(float(ep["total_voiced_ms"]) + voiced_ms, 1)
            if location and not ep.get("location"):
                ep["location"] = dict(location)
        else:
            ep = {
                "episode_id": f"ep-{int(now_s * 1000)}-{uuid.uuid4().hex[:4]}",
                "node_id": clean_node,
                "start_timestamp": now_s,
                "end_timestamp": now_s,
                "segment_ids": [seg_id],
                "transcripts": [text],
                "full_text": text,
                "total_voiced_ms": round(voiced_ms, 1),
            }
            if location:
                ep["location"] = dict(location)
            node_episodes.append(ep)

        # Extract follow-up tasks & deduplicate against existing open tasks for this node
        node_tasks = self.tasks.setdefault(clean_node, [])
        existing_titles = {t["title"].lower() for t in node_tasks}
        candidates = extract_followup_tasks(text)
        new_tasks: List[Dict[str, Any]] = []
        for cand in candidates:
            if cand["title"].lower() not in existing_titles:
                existing_titles.add(cand["title"].lower())
                task_obj = {
                    "task_id": f"task-{uuid.uuid4().hex[:8]}",
                    "node_id": clean_node,
                    "episode_id": ep["episode_id"],
                    "segment_id": seg_id,
                    "title": cand["title"],
                    "category": cand["category"],
                    "source_quote": cand["source_quote"],
                    "status": "open",
                    "created_at": iso_ts,
                }
                node_tasks.append(task_obj)
                new_tasks.append(task_obj)

        return {
            "ok": True,
            "node_id": clean_node,
            "segment_id": seg_id,
            "episode_id": ep["episode_id"],
            "ghost_filtered": False,
            "voiced_ms": round(voiced_ms, 1),
            "transcript": text,
            "location": segment_entry.get("location"),
            "tasks_extracted": new_tasks,
        }

    def get_journal(self, node_id: str) -> Dict[str, Any]:
        """Returns the current segments, conversation episodes, and follow-up tasks for `node_id`."""
        clean_node = validate_node_id(node_id or "gotchi-device")
        segs = list(self.segments.get(clean_node, []))
        eps = list(self.episodes.get(clean_node, []))
        tasks = list(self.tasks.get(clean_node, []))
        total_voiced_ms = round(sum(float(s.get("voiced_ms", 0.0)) for s in segs), 1)
        return {
            "ok": True,
            "node_id": clean_node,
            "segment_count": len(segs),
            "episode_count": len(eps),
            "total_voiced_ms": total_voiced_ms,
            "episodes": eps,
            "tasks": tasks,
            "segments": segs,
        }

    def summarize_day(self, node_id: str) -> Dict[str, Any]:
        """
        Generates a structured daily journal summary and organized follow-up task list
        from all captured conversation episodes for `node_id`.
        """
        state = self.get_journal(node_id)
        eps = state["episodes"]
        tasks = state["tasks"]

        if self.llm_distiller is not None:
            distilled = self.llm_distiller(eps)
            summary_text = str(distilled.get("summary", "")).strip()
            extra_tasks = distilled.get("tasks") or []
            existing_titles = {t["title"].lower() for t in tasks}
            for item in extra_tasks:
                title = str(item.get("title") if isinstance(item, dict) else item).strip()
                if title and title.lower() not in existing_titles:
                    existing_titles.add(title.lower())
                    task_obj = {
                        "task_id": f"task-{uuid.uuid4().hex[:8]}",
                        "node_id": state["node_id"],
                        "episode_id": eps[-1]["episode_id"] if eps else "",
                        "segment_id": "",
                        "title": title,
                        "category": item.get("category", "task") if isinstance(item, dict) else "task",
                        "source_quote": "",
                        "status": "open",
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
                    }
                    self.tasks.setdefault(state["node_id"], []).append(task_obj)
                    tasks.append(task_obj)
        else:
            if not eps:
                summary_text = "No conversation episodes recorded today."
            else:
                highlights = [ep["full_text"] for ep in eps]
                summary_text = (
                    f"{len(eps)} conversation episode(s) recorded "
                    f"({len(tasks)} follow-up task(s)): " + " | ".join(highlights)
                )

        open_tasks = [t for t in tasks if t.get("status") == "open"]
        return {
            "ok": True,
            "node_id": state["node_id"],
            "summary": summary_text,
            "episode_count": len(eps),
            "open_task_count": len(open_tasks),
            "tasks": tasks,
            "episodes": eps,
        }

    def update_task_status(self, node_id: str, task_id: str, status: str) -> Dict[str, Any]:
        """Updates a follow-up task's status ('open' | 'done' | 'dismissed')."""
        clean_node = validate_node_id(node_id or "gotchi-device")
        if status not in ("open", "done", "dismissed"):
            raise ValueError(f"Invalid task status '{status}'; expected open | done | dismissed")
        for t in self.tasks.get(clean_node, []):
            if t["task_id"] == task_id:
                t["status"] = status
                return {"ok": True, "task": t}
        raise KeyError(f"Task '{task_id}' not found for node '{clean_node}'")


def register_journal_routes(app: "FastAPI", journal_srv: JournalService) -> None:
    """Mounts `/api/journal/ingest`, `/api/journal/entries`, `/api/journal/summarize`, and `/api/journal/tasks/{task_id}`."""

    def _check_auth(request: Request) -> Tuple[bool, int, Dict[str, Any]]:
        if journal_srv.auth_required or journal_srv.verifier.device_tokens:
            headers = dict(request.headers)
            client_ip = request.client.host if request.client else "0.0.0.0"
            return journal_srv.verifier.verify(headers, client_ip=client_ip)
        return True, 200, {}

    def _parse_location(raw_lat: Any, raw_lon: Any, raw_acc: Any = None) -> Optional[Dict[str, float]]:
        if raw_lat is None or raw_lon is None or str(raw_lat).strip() == "" or str(raw_lon).strip() == "":
            return None
        lat_val = float(str(raw_lat).strip())
        lon_val = float(str(raw_lon).strip())
        if not (-90.0 <= lat_val <= 90.0) or not (-180.0 <= lon_val <= 180.0):
            raise ValueError("Coordinates out of range: lat must be [-90, 90], lon must be [-180, 180]")
        loc: Dict[str, float] = {"lat": round(lat_val, 6), "lon": round(lon_val, 6)}
        if raw_acc is not None and str(raw_acc).strip() != "":
            try:
                acc_val = float(str(raw_acc).strip())
                if acc_val >= 0.0:
                    loc["accuracy_m"] = round(acc_val, 1)
            except ValueError:
                pass
        return loc

    @app.post("/api/journal/ingest")
    async def journal_ingest(request: Request):
        ok, code, err = _check_auth(request)
        if not ok:
            return JSONResponse(status_code=code, content=err)

        ctype = (request.headers.get("content-type") or "").lower()
        try:
            if "application/json" in ctype:
                body = await request.json()
                node_id = body.get("node_id") or "gotchi-device"
                transcript = body.get("transcript") or body.get("prompt")
                session_id = body.get("session_id")
                transport = body.get("transport") or "wifi"
                audio_b64 = body.get("audio_b64")
                import base64 as _b64
                audio_bytes = _b64.b64decode(audio_b64) if audio_b64 else None
                location = _parse_location(body.get("lat"), body.get("lon"), body.get("location_accuracy_m"))
                res = journal_srv.ingest_segment(
                    node_id=node_id,
                    audio_bytes=audio_bytes,
                    transcript=transcript,
                    session_id=session_id,
                    transport=transport,
                    location=location,
                )
            else:
                form = await request.form()
                node_id = str(form.get("node_id") or "gotchi-device")
                transcript = form.get("transcript") or form.get("prompt")
                session_id = form.get("session_id")
                transport = str(form.get("transport") or "wifi")
                audio_bytes = _read_part_bytes(form["audio"]) if "audio" in form else None
                location = _parse_location(form.get("lat"), form.get("lon"), form.get("location_accuracy_m"))
                res = journal_srv.ingest_segment(
                    node_id=node_id,
                    audio_bytes=audio_bytes,
                    transcript=str(transcript) if transcript is not None else None,
                    session_id=str(session_id) if session_id is not None else None,
                    transport=transport,
                    location=location,
                )
            return JSONResponse(status_code=200, content=res)
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"ok": False, "error": "bad_request", "message": str(ve)})

    @app.get("/api/journal/entries")
    def journal_entries(request: Request, node_id: str = "gotchi-v1-01"):
        ok, code, err = _check_auth(request)
        if not ok:
            return JSONResponse(status_code=code, content=err)
        try:
            return journal_srv.get_journal(node_id)
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"ok": False, "error": "bad_request", "message": str(ve)})

    @app.post("/api/journal/summarize")
    async def journal_summarize(request: Request):
        ok, code, err = _check_auth(request)
        if not ok:
            return JSONResponse(status_code=code, content=err)
        try:
            body = await request.json() if (request.headers.get("content-length") not in (None, "0")) else {}
            node_id = (body.get("node_id") if isinstance(body, dict) else None) or request.query_params.get("node_id") or "gotchi-v1-01"
            return journal_srv.summarize_day(str(node_id))
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"ok": False, "error": "bad_request", "message": str(ve)})

    @app.patch("/api/journal/tasks/{task_id}")
    async def journal_update_task(task_id: str, request: Request):
        ok, code, err = _check_auth(request)
        if not ok:
            return JSONResponse(status_code=code, content=err)
        try:
            body = await request.json()
            node_id = body.get("node_id") or "gotchi-v1-01"
            status = body.get("status") or "done"
            return journal_srv.update_task_status(str(node_id), task_id, str(status))
        except KeyError as ke:
            return JSONResponse(status_code=404, content={"ok": False, "error": "not_found", "message": str(ke)})
        except ValueError as ve:
            return JSONResponse(status_code=400, content={"ok": False, "error": "bad_request", "message": str(ve)})
