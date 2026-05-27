from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_USER_PROGRESS_LOCK = RLock()


class UserProgressLogger:
    """Runtime-native user progress stream, independent from any UI client."""

    def __init__(
        self,
        path: Path,
        validator: SchemaValidator | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        self.path = path
        self.store = JsonlStore(validator)
        self.session_id = session_id
        self._counter = self._load_existing_count()

    def record(
        self,
        *,
        run_id: str | None,
        channel: str = "progress",
        event_type: str = "message",
        phase: str,
        status: str,
        title: str,
        summary: str,
        content_delta: str = "",
        display_level: str = "main",
        parent_event_id: str | None = None,
        tool_call_id: str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        command: list[str] | None = None,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        telemetry: dict[str, Any] | None = None,
        call_chain: list[str] | None = None,
        execution_chain: list[str] | None = None,
        file_changes: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with _USER_PROGRESS_LOCK:
            self._counter += 1
            event = {
                "schema_version": "0.1.0",
                "event_id": f"upe-{self._counter:04d}",
                "run_id": run_id,
                "session_id": self.session_id,
                "created_at": now_iso(),
                "sequence": self._counter,
                "channel": channel,
                "event_type": event_type,
                "parent_event_id": parent_event_id,
                "tool_call_id": tool_call_id,
                "phase": phase,
                "status": status,
                "title": title,
                "summary": summary,
                "content_delta": content_delta,
                "display_level": display_level,
                "model_provider": model_provider,
                "model_name": model_name,
                "command": command or [],
                "artifact_refs": artifact_refs or [],
                "evidence_refs": evidence_refs or [],
                "telemetry": telemetry or {},
                "call_chain": call_chain or [],
                "execution_chain": execution_chain or [],
                "file_changes": file_changes or [],
                "data": data or {},
            }
            self.store.append(self.path, event, "user_progress_event")
            return event

    def conclusion(
        self,
        *,
        run_id: str | None,
        phase: str,
        title: str,
        summary: str,
        content_delta: str = "",
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="conclusion",
            event_type="message",
            phase=phase,
            status="completed",
            title=title,
            summary=summary,
            content_delta=content_delta,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
        )

    def heartbeat(
        self,
        *,
        run_id: str | None,
        phase: str,
        title: str,
        summary: str,
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="diagnostic",
            event_type="heartbeat",
            phase=phase,
            status="running",
            title=title,
            summary=summary,
            display_level="inspector",
        )

    def artifact_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        artifact_refs: list[str],
        phase: str = "execute",
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="evidence",
            event_type="evidence",
            phase=phase,
            status="completed",
            title=title,
            summary=summary,
            artifact_refs=artifact_refs,
            evidence_refs=artifact_refs,
            display_level="inspector",
        )

    def workspace_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        workspace: dict[str, Any],
        phase: str = "understand",
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="workspace",
            event_type="workspace_selected",
            phase=phase,
            status="completed",
            title=title,
            summary=summary,
            data={"workspace": workspace},
        )

    def permission_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        permission: dict[str, Any],
        status: str = "completed",
        phase: str = "understand",
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="permission",
            event_type="permission_decision",
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            data={"permission": permission},
        )

    def read_all(self) -> list[dict[str, Any]]:
        return self.store.read_all(self.path, "user_progress_event")

    def _load_existing_count(self) -> int:
        if not self.path.exists():
            return 0
        return len(JsonlStore().read_all(self.path))
