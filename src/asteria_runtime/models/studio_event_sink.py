from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from asteria_runtime.utils.time import now_iso


_LOCK = RLock()


class StudioModelEventSink:
    """Best-effort bridge from provider streaming to Asteria Studio sessions."""

    def __init__(self) -> None:
        self.path = Path(os.environ["ASTERIA_STUDIO_EVENT_SINK"]) if os.getenv("ASTERIA_STUDIO_EVENT_SINK") else None
        self.session_id = os.getenv("ASTERIA_STUDIO_SESSION_ID")
        self.phase = os.getenv("ASTERIA_STUDIO_PHASE") or "plan"
        self.enabled = self.path is not None and bool(self.session_id)
        self._start_event_id: str | None = None

    def model_start(self, *, provider: str, model: str | None, mode: str) -> None:
        event = self._append(
            {
                "type": "model_start",
                "status": "running",
                "title": _title_for_phase(self.phase, "start"),
                "summary": f"{provider}/{model or 'unknown'} is returning {_label_for_phase(self.phase)}.",
                "content_delta": "",
                "phase": self.phase,
                "display_level": "main",
                "model_provider": provider,
                "model_name": model,
                "streaming_mode": mode,
            }
        )
        self._start_event_id = str(event["event_id"]) if event else None

    def model_delta(self, text: str, *, provider: str, model: str | None) -> None:
        if not text:
            return
        self._append(
            {
                "type": "model_delta",
                "status": "running",
                "title": _title_for_phase(self.phase, "delta"),
                "summary": f"Receiving {_label_for_phase(self.phase)} content.",
                "content_delta": text,
                "phase": self.phase,
                "display_level": "main",
                "parent_event_id": self._start_event_id,
                "model_provider": provider,
                "model_name": model,
            }
        )

    def model_end(self, *, provider: str, model: str | None, telemetry: dict[str, Any] | None = None) -> None:
        chunks = (telemetry or {}).get("chunk_count")
        duration = (telemetry or {}).get("duration_ms")
        summary_parts = []
        if chunks is not None:
            summary_parts.append(f"chunks={chunks}")
        if duration is not None:
            summary_parts.append(f"duration_ms={duration}")
        self._append(
            {
                "type": "model_end",
                "status": "completed",
                "title": _title_for_phase(self.phase, "end"),
                "summary": " / ".join(summary_parts) if summary_parts else f"{_label_for_phase(self.phase)} completed.",
                "content_delta": "",
                "phase": self.phase,
                "display_level": "main",
                "parent_event_id": self._start_event_id,
                "model_provider": provider,
                "model_name": model,
                "telemetry": telemetry or {},
            }
        )

    def model_error(self, *, provider: str, model: str | None, error: str) -> None:
        self._append(
            {
                "type": "model_error",
                "status": "failed",
                "title": "Model response failed",
                "summary": error[:240],
                "content_delta": error,
                "phase": self.phase,
                "display_level": "main",
                "parent_event_id": self._start_event_id,
                "model_provider": provider,
                "model_name": model,
            }
        )

    def _append(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled or self.path is None:
            return None
        full = {
            "schema_version": "0.1.0",
            "event_id": f"evt-model-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "session_id": self.session_id,
            "created_at": now_iso(),
            "artifact_refs": [],
            "evidence_refs": [],
            **_redact(event),
        }
        try:
            with _LOCK:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(full, ensure_ascii=False) + "\n")
            return full
        except OSError:
            return None

def studio_model_event_sink() -> StudioModelEventSink:
    return StudioModelEventSink()


def _redact(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return value.replace("Bearer ", "Bearer [REDACTED] ")
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("api_key", "apikey", "authorization", "token", "secret", "password"))


def _label_for_phase(phase: str) -> str:
    return {
        "understand": "goal understanding",
        "chat": "chat response",
        "plan": "plan",
        "execute": "execution feedback",
        "review": "review result",
        "resume": "resume feedback",
        "result": "result",
        "next": "next-step advice",
    }.get(phase, "task feedback")


def _title_for_phase(phase: str, event: str) -> str:
    labels = {
        "understand": "Understanding goal",
        "chat": "Chat response",
        "plan": "Planning",
        "execute": "Executing task",
        "review": "Reviewing result",
        "resume": "Resuming",
        "result": "Preparing result",
        "next": "Next step",
    }
    suffix = {"start": " started", "delta": " update", "end": " completed"}.get(event, "")
    return f"{labels.get(phase, 'Task progress')}{suffix}"
