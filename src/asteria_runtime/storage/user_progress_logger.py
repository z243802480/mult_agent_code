from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_USER_PROGRESS_LOCK = RLock()
_TRANSCRIPT_KINDS = {
    "user_message",
    "assistant_message",
    "plan",
    "todo_update",
    "tool_use",
    "tool_result",
    "file_change",
    "verification",
    "permission_request",
    "decision_request",
    "repair",
    "ask",
    "stop",
    "final",
    "context_status",
    "subagent_summary",
    "progress",
    "diagnostic",
}
_MAIN_COPY_REPLACEMENTS = {
    "provider route blocked": "model connection interrupted",
    "model-check": "connection check",
    "gate-status": "diagnostics",
    "runtime_progress": "progress",
    "user_progress.jsonl": "progress log",
    "agent_loop_execution_results.jsonl": "agent step evidence",
    "agent_loop_decisions.jsonl": "agent decision evidence",
    "agent_loop_observations.jsonl": "agent observation evidence",
}


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
        transcript_kind: str | None = None,
        ui_intent: str | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with _USER_PROGRESS_LOCK:
            self._counter += 1
            safe_title, safe_summary, safe_content_delta = self._main_copy(
                display_level=display_level,
                title=title,
                summary=summary,
                content_delta=content_delta,
            )
            safe_transcript_kind = self._transcript_kind(
                transcript_kind=transcript_kind,
                channel=channel,
                event_type=event_type,
                phase=phase,
            )
            safe_title, safe_summary, safe_content_delta = self._repair_corrupt_main_copy(
                display_level=display_level,
                transcript_kind=safe_transcript_kind,
                phase=phase,
                status=status,
                title=safe_title,
                summary=safe_summary,
                content_delta=safe_content_delta,
            )
            event = {
                "schema_version": "0.1.0",
                "event_id": f"upe-{self._counter:04d}",
                "run_id": run_id,
                # Fall back to the run's own id as its session identity when no session was bound:
                # the runtime models session==run (run_dir==session_dir), so writing null here was a
                # dishonest "no session" on every event. An explicitly-bound session_id still wins.
                "session_id": self.session_id or run_id,
                "created_at": now_iso(),
                "sequence": self._counter,
                "channel": channel,
                "event_type": event_type,
                "parent_event_id": parent_event_id,
                "tool_call_id": tool_call_id,
                "phase": phase,
                "status": status,
                "title": safe_title,
                "summary": safe_summary,
                "content_delta": safe_content_delta,
                "display_level": display_level,
                "transcript_kind": safe_transcript_kind,
                "ui_intent": ui_intent or self._ui_intent(safe_transcript_kind, status),
                "actions": actions or self._default_actions(
                    title=safe_title,
                    summary=safe_summary,
                    data=data or {},
                ),
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

    def _main_copy(
        self,
        *,
        display_level: str,
        title: str,
        summary: str,
        content_delta: str,
    ) -> tuple[str, str, str]:
        if display_level != "main":
            return title, summary, content_delta
        if self._looks_like_provider_blocker(title, summary, content_delta):
            return (
                "Model connection interrupted",
                (
                    "The model connection failed before Asteria received an executable step. "
                    "No repair was started; check the connection and retry when it recovers."
                ),
                "",
            )
        return (
            self._replace_backend_terms(title),
            self._replace_backend_terms(summary),
            self._replace_backend_terms(content_delta),
        )

    def _looks_like_provider_blocker(self, *values: str) -> bool:
        text = "\n".join(str(value or "") for value in values).lower()
        return (
            "provider route blocked" in text
            or "provider/network" in text
            or "provider_transient" in text
            or "provider_network" in text
            or "model-check" in text
        )

    def _replace_backend_terms(self, value: str) -> str:
        result = str(value or "")
        for raw, replacement in _MAIN_COPY_REPLACEMENTS.items():
            result = result.replace(raw, replacement)
            result = result.replace(raw.upper(), replacement)
        return result

    def _repair_corrupt_main_copy(
        self,
        *,
        display_level: str,
        transcript_kind: str,
        phase: str,
        status: str,
        title: str,
        summary: str,
        content_delta: str,
    ) -> tuple[str, str, str]:
        if display_level != "main":
            return title, summary, content_delta
        if not self._looks_corrupt_copy(title, summary, content_delta):
            return title, summary, content_delta
        fallback_title, fallback_summary = self._fallback_main_copy(
            transcript_kind=transcript_kind,
            phase=phase,
            status=status,
        )
        return fallback_title, fallback_summary, ""

    def _looks_corrupt_copy(self, *values: str) -> bool:
        text = "\n".join(str(value or "") for value in values)
        if not text.strip():
            return False
        if "�" in text or "€" in text:
            return True
        mojibake_markers = (
            "銆",
            "锛",
            "绛",
            "浠",
            "璇",
            "妫",
            "闃",
            "鎵",
            "姝",
            "鍒",
            "鐞",
            "鑳",
            "藉",
            "勫",
            "垝",
            "渶",
        )
        return sum(1 for marker in mojibake_markers if marker in text) >= 2

    def _fallback_main_copy(
        self,
        *,
        transcript_kind: str,
        phase: str,
        status: str,
    ) -> tuple[str, str]:
        if transcript_kind in {"plan", "todo_update"}:
            return "Plan ready", "Asteria prepared the plan and is ready to continue."
        if transcript_kind == "tool_use":
            return "Using a tool", "Asteria started a tool step for the current task."
        if transcript_kind == "tool_result":
            return "Tool step updated", "Asteria recorded the latest tool result."
        if transcript_kind == "file_change":
            return "File change recorded", "Asteria recorded file changes for this run."
        if transcript_kind == "verification":
            return "Verification updated", "Asteria checked the latest result and recorded the outcome."
        if transcript_kind == "repair":
            return "Repair updated", "Asteria attempted recovery and recorded what changed."
        if transcript_kind in {"permission_request", "decision_request", "ask"}:
            return "Decision needed", "Asteria needs input before it can safely continue."
        if transcript_kind in {"final", "stop"}:
            return "Result ready", "Asteria recorded the result and the next available step."
        if status in {"failed", "blocked"}:
            return "Needs attention", "Asteria stopped at a point that needs recovery or input."
        if phase == "review":
            return "Verification updated", "Asteria checked the latest result and recorded the outcome."
        return "Progress updated", "Asteria recorded progress for the current run."

    def _transcript_kind(
        self,
        *,
        transcript_kind: str | None,
        channel: str,
        event_type: str,
        phase: str,
    ) -> str:
        if transcript_kind in _TRANSCRIPT_KINDS:
            return transcript_kind
        if channel == "tool":
            return "tool_result" if event_type in {"tool_output", "tool_observation", "end", "error"} else "tool_use"
        if channel == "file":
            return "file_change"
        if channel == "validation":
            return "verification"
        if channel == "permission":
            return "permission_request" if event_type == "permission_request" else "decision_request"
        if channel == "conclusion":
            # A "conclusion" channel is only the run's real conclusion when it reports a result.
            # Some runs (e.g. plan_command) open on the conclusion channel with phase="understand";
            # mapping that opening event to "final" made latest_main_final_event pick the FIRST
            # step as the run's outcome. Require phase=="result" so only genuine finals qualify.
            return "final" if phase == "result" else "progress"
        if channel == "diagnostic":
            return "diagnostic"
        if event_type == "decision":
            return "decision_request"
        if phase == "blocked":
            return "ask"
        if phase == "plan":
            return "plan"
        if phase == "review":
            return "verification"
        if phase == "result":
            return "final"
        if phase == "next":
            return "progress"
        return "progress"

    def _ui_intent(self, transcript_kind: str, status: str) -> str:
        if status in {"failed", "blocked"}:
            return "needs_attention"
        if status == "waiting_user":
            return "needs_input"
        if transcript_kind in {"permission_request", "decision_request", "ask"}:
            return "needs_input"
        if transcript_kind in {"final", "stop"}:
            return "result"
        if transcript_kind in {"plan", "todo_update", "tool_use", "tool_result", "file_change", "verification", "subagent_summary"}:
            return "work_progress"
        return "inform"

    def _default_actions(
        self,
        *,
        title: str,
        summary: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text = f"{title}\n{summary}\n{data}".lower()
        if "model connection interrupted" in text or "model-check" in text:
            return [
                {
                    "kind": "connection_check",
                    "label": "Check connection",
                    "command": "model-check --tier medium",
                },
                {
                    "kind": "continue",
                    "label": "Retry run",
                    "command": "run --resume",
                },
            ]
        if "pending_decision_ids" in text or "decision_id" in text:
            return [
                {
                    "kind": "decision",
                    "label": "Decide",
                    "command": "decide --list",
                }
            ]
        return []

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
            transcript_kind="final",
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
            transcript_kind="diagnostic",
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
        output_locations: dict[str, Any] | None = None,
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
            data={"workspace": workspace, "output_locations": output_locations or {}},
            transcript_kind="progress",
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
            transcript_kind="decision_request",
        )

    def decision_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        decision: dict[str, Any],
        status: str = "completed",
        phase: str = "review",
        display_level: str = "main",
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="progress",
            event_type="decision",
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            display_level=display_level,
            data={"decision": decision},
            transcript_kind="decision_request",
        )

    def model_decision_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        model_selection: dict[str, Any],
        phase: str = "execute",
        status: str = "completed",
        display_level: str = "inspector",
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="model",
            event_type="model_decision",
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            display_level=display_level,
            data={"model_selection": model_selection},
            call_chain=["RunCommand"],
            execution_chain=[phase, "model_selection"],
            transcript_kind="diagnostic",
            ui_intent="inform",
        )

    def file_change_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        file_changes: list[dict[str, Any]],
        phase: str = "execute",
        status: str = "completed",
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="file",
            event_type="file_changed",
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            file_changes=file_changes,
            data={"changed_file_count": len(file_changes)},
            call_chain=["RunCommand"],
            execution_chain=[phase, "file_changes"],
            transcript_kind="file_change",
        )

    def validation_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        validation: dict[str, Any],
        phase: str = "review",
        status: str = "completed",
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.record(
            run_id=run_id,
            channel="validation",
            event_type="validation_result",
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            evidence_refs=evidence_refs,
            data={"validation": validation},
            call_chain=["RunCommand"],
            execution_chain=[phase, "validation"],
            display_level="main",
            ui_intent="work_progress",
            transcript_kind="verification",
        )

    def final_report_event(
        self,
        *,
        run_id: str | None,
        title: str,
        summary: str,
        final_report_path: str,
        final_report_summary_path: str | None = None,
        output_locations: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        model_selection: dict[str, Any] | None = None,
        file_changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        refs = [final_report_path]
        if final_report_summary_path:
            refs.append(final_report_summary_path)
        return self.record(
            run_id=run_id,
            channel="conclusion",
            event_type="final_report",
            phase="result",
            status="completed",
            title=title,
            summary=summary,
            artifact_refs=refs,
            evidence_refs=refs,
            file_changes=file_changes or [],
            data={
                "final_report_path": final_report_path,
                "final_report_summary_path": final_report_summary_path,
                "output_locations": output_locations or {},
                "validation": validation or {},
                "model_selection": model_selection or {},
            },
            call_chain=["RunCommand"],
            execution_chain=["result", "final_report"],
            display_level="main",
            ui_intent="result",
            transcript_kind="final",
        )

    def read_all(self) -> list[dict[str, Any]]:
        return self.store.read_all(self.path, "user_progress_event")

    def _load_existing_count(self) -> int:
        if not self.path.exists():
            return 0
        return len(JsonlStore().read_all(self.path))
