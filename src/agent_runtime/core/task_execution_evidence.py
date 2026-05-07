from __future__ import annotations

from pathlib import Path

from agent_runtime.core.candidate_workspace import CandidateWorkspace
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class TaskExecutionEvidenceRecorder:
    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator

    def record(
        self,
        context: RuntimeContext,
        task: dict,
        action: dict | None,
        tool_results: list,
        verification_results: list,
        status: str,
        summary: str,
        *,
        actor: str,
        contract_check: dict | None = None,
        candidate_workspace: CandidateWorkspace | None = None,
        promoted_files: list[str] | None = None,
        candidate: dict | None = None,
        failure_type: str | None = None,
    ) -> Path | None:
        if not context.run_dir:
            return None
        path = context.run_dir / "task_execution_evidence.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "task_execution_evidence") if path.exists() else []
        record = {
            "schema_version": "0.1.0",
            "evidence_id": f"task-execution-{len(existing) + 1:04d}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "status": status,
            "summary": summary,
            "failure_type": failure_type,
            "task": {
                "title": task.get("title"),
                "task_kind": task.get("task_kind"),
                "acceptance": task.get("acceptance", []),
                "expected_artifacts": task.get("expected_artifacts", []),
                "expected_changed_files": task.get("expected_changed_files", []),
                "allowed_tools": task.get("allowed_tools", []),
            },
            "action": {
                "summary": (action or {}).get("summary"),
                "tool_count": len((action or {}).get("tool_calls", [])),
                "verification_count": len((action or {}).get("verification", [])),
                "completion_notes": (action or {}).get("completion_notes"),
            },
            "candidate": {
                "workspace": str(candidate_workspace.root) if candidate_workspace else None,
                "candidate_id": candidate_workspace.candidate_id if candidate_workspace else None,
                "changed_files": self._changed_files(tool_results),
                "promoted_files": sorted(set(promoted_files or [])),
                **(candidate or {}),
            },
            "contract_check": contract_check or {},
            "tool_results": self._result_evidence(tool_results),
            "verification_results": self._result_evidence(verification_results),
            "created_at": now_iso(),
        }
        store.append(path, record, "task_execution_evidence")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_execution_evidence_recorded",
                actor,
                f"{record['evidence_id']} -> {status}",
                {
                    "evidence_id": record["evidence_id"],
                    "task_id": task["task_id"],
                    "status": status,
                    "artifact": str(path),
                },
            )
        return path

    def _changed_files(self, tool_results: list) -> list[str]:
        changed_files = []
        for result in tool_results:
            if not getattr(result, "ok", False):
                continue
            data = getattr(result, "data", {})
            if not isinstance(data, dict):
                continue
            if data.get("path"):
                changed_files.append(data["path"])
            changed_files.extend(data.get("changed_files", []))
        return changed_files

    def _result_evidence(self, results: list) -> list[dict]:
        evidence = []
        for result in results:
            data = getattr(result, "data", {})
            evidence.append(
                {
                    "ok": bool(getattr(result, "ok", False)),
                    "summary": str(getattr(result, "summary", "")),
                    "error": getattr(result, "error", None),
                    "warnings": list(getattr(result, "warnings", []) or []),
                    "data": data if isinstance(data, dict) else {},
                }
            )
        return evidence
