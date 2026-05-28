from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from asteria_runtime.core.capability_decision_recorder import CapabilityDecisionRecorder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


class SkillHandler(Protocol):
    def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class SkillArtifact:
    path: str
    type: str = "artifact"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "type": self.type, "summary": self.summary}


@dataclass(frozen=True)
class SkillInvocationResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[SkillArtifact] = field(default_factory=list)
    error: str | None = None
    status: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "error": self.error,
            "status": self.status,
        }


class SkillAdapter:
    """Workflow/artifact skill adapter; not a local ToolExecutionGateway wrapper."""

    def __init__(
        self,
        handlers: dict[str, SkillHandler],
        *,
        actor: str = "SkillAdapter",
    ) -> None:
        self.handlers = handlers
        self.actor = actor

    def invoke(
        self,
        *,
        context: RuntimeContext,
        task: dict[str, Any],
        skill_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> SkillInvocationResult:
        invocation_id = self._next_invocation_id(context)
        decision = CapabilityDecisionRecorder(self.actor).decide_skill(
            skill_name,
            task=task,
            context=context,
            skill_invocation_id=invocation_id,
        )
        args = arguments or {}
        if decision["decision"] == "deny":
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill denied: {skill_name}",
                error=decision["reason"],
                status="denied",
            )
            self._record_invocation(context, task, invocation_id, skill_name, args, decision, result)
            return result
        handler = self.handlers.get(skill_name)
        if handler is None:
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill handler not configured: {skill_name}",
                error="skill_handler_not_configured",
                status="config_error",
            )
            self._record_invocation(context, task, invocation_id, skill_name, args, decision, result)
            return result
        try:
            payload = handler.invoke(
                {
                    "skill_name": skill_name,
                    "arguments": args,
                    "task": task,
                    "run_id": context.run_id,
                    "root": str(context.root),
                    "run_dir": str(context.run_dir) if context.run_dir else None,
                }
            )
            result = self._result_from_payload(skill_name, payload)
        except Exception as exc:  # noqa: BLE001 - adapter boundary returns structured failure
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill failed: {skill_name}",
                error=str(exc),
                status="execution_error",
            )
        self._record_invocation(context, task, invocation_id, skill_name, args, decision, result)
        return result

    def _result_from_payload(self, skill_name: str, payload: dict[str, Any]) -> SkillInvocationResult:
        raw_artifacts = payload.get("artifacts")
        artifacts: list[SkillArtifact] = []
        if isinstance(raw_artifacts, list):
            for item in raw_artifacts:
                if isinstance(item, str):
                    artifacts.append(SkillArtifact(path=item))
                elif isinstance(item, dict) and item.get("path"):
                    artifacts.append(
                        SkillArtifact(
                            path=str(item["path"]),
                            type=str(item.get("type") or "artifact"),
                            summary=str(item.get("summary") or ""),
                        )
                    )
        ok = bool(payload.get("ok", True))
        return SkillInvocationResult(
            ok=ok,
            summary=str(payload.get("summary") or f"Skill completed: {skill_name}"),
            data=(
                payload["data"]
                if isinstance(payload.get("data"), dict)
                else {}
            ),
            artifacts=artifacts,
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
            status=str(payload.get("status") or ("success" if ok else "failure")),
        )

    def _record_invocation(
        self,
        context: RuntimeContext,
        task: dict[str, Any],
        invocation_id: str,
        skill_name: str,
        arguments: dict[str, Any],
        decision: dict[str, Any],
        result: SkillInvocationResult,
    ) -> None:
        if context.run_dir is None:
            return
        artifact_refs = self._record_artifacts(context, task, skill_name, result)
        path = context.run_dir / "skill_invocations.jsonl"
        record = {
            "schema_version": "0.1.0",
            "skill_invocation_id": invocation_id,
            "run_id": context.run_id,
            "task_id": str(task.get("task_id", "")),
            "skill_name": skill_name,
            "arguments": self._safe_arguments(arguments),
            "capability_decision": decision,
            "status": result.status,
            "ok": result.ok,
            "summary": result.summary,
            "error": result.error,
            "data": result.data,
            "artifacts": [artifact.to_dict() for artifact in result.artifacts],
            "artifact_refs": artifact_refs,
            "created_at": now_iso(),
        }
        JsonlStore(context.validator).append(path, record, schema_name=None)
        UserProgressLogger(path.with_name("user_progress.jsonl"), context.validator).record(
            run_id=context.run_id,
            channel="tool",
            event_type="tool_output",
            phase="execute",
            status=self._progress_status(result),
            title=f"Skill {skill_name}",
            summary=result.summary,
            artifact_refs=artifact_refs,
            data={
                "adapter": "skill_workflow_artifact",
                "capability_type": "skill",
                "skill_invocation": record,
                "capability_decision": decision,
            },
            evidence_refs=[str(path), str(context.run_dir / "capability_decisions.jsonl")],
            call_chain=[self.actor, skill_name],
            execution_chain=[str(task.get("task_id", "")), "skill", skill_name],
        )

    def _record_artifacts(
        self,
        context: RuntimeContext,
        task: dict[str, Any],
        skill_name: str,
        result: SkillInvocationResult,
    ) -> list[str]:
        if context.run_dir is None or not result.artifacts:
            return []
        path = context.run_dir / "artifacts.jsonl"
        store = JsonlStore(context.validator)
        existing = store.read_all(path, "artifact") if path.exists() else []
        known = {artifact["path"]: artifact["artifact_id"] for artifact in existing}
        next_index = self._next_artifact_index(existing)
        refs: list[str] = []
        workspace = context.policy.get("workspace_envelope") or {}
        for skill_artifact in result.artifacts:
            if skill_artifact.path in known:
                refs.append(known[skill_artifact.path])
                continue
            artifact_id = f"artifact-{next_index:04d}"
            artifact = {
                "schema_version": "0.1.0",
                "artifact_id": artifact_id,
                "run_id": context.run_id,
                "task_id": str(task.get("task_id", "")),
                "type": skill_artifact.type,
                "path": skill_artifact.path,
                "absolute_path": str((context.root / skill_artifact.path).resolve()),
                "workspace_id": workspace.get("workspace_id"),
                "output_root": workspace.get("output_root"),
                "artifact_root": workspace.get("artifact_root"),
                "created_by": f"SkillAdapter:{skill_name}",
                "summary": skill_artifact.summary or result.summary,
                "created_at": now_iso(),
            }
            store.append(path, artifact, "artifact")
            refs.append(artifact_id)
            known[skill_artifact.path] = artifact_id
            next_index += 1
        return refs

    def _next_invocation_id(self, context: RuntimeContext) -> str:
        if context.run_dir is None:
            return "skill-0001"
        path = context.run_dir / "skill_invocations.jsonl"
        count = len(JsonlStore(context.validator).read_all(path, schema_name=None)) if path.exists() else 0
        return f"skill-{count + 1:04d}"

    def _next_artifact_index(self, existing: list[dict[str, Any]]) -> int:
        highest = 0
        for artifact in existing:
            raw_id = str(artifact.get("artifact_id") or "")
            prefix, _, suffix = raw_id.partition("-")
            if prefix == "artifact" and suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def _safe_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            key: ("<redacted>" if self._sensitive_key(key) else value)
            for key, value in arguments.items()
        }

    def _progress_status(self, result: SkillInvocationResult) -> str:
        if result.ok:
            return "completed"
        if result.status == "denied":
            return "blocked"
        return "failed"

    def _sensitive_key(self, key: str) -> bool:
        normalized = key.lower()
        return any(part in normalized for part in ["token", "secret", "password", "api_key"])
