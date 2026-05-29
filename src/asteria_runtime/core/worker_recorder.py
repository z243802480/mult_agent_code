from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class WorkerExecutionSlot:
    worker_id: str
    result_id: str


@dataclass(frozen=True)
class WorkerExecutionRecorder:
    validator: SchemaValidator

    def allocate_worker_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-{index + 1:04d}" for index in range(count)]
        start = self._jsonl_count(context.run_dir / "workers.jsonl") + 1
        return [f"worker-{index:04d}" for index in range(start, start + count)]

    def allocate_worker_result_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-result-{index + 1:04d}" for index in range(count)]
        start = self._jsonl_count(context.run_dir / "worker_results.jsonl") + 1
        return [f"worker-result-{index:04d}" for index in range(start, start + count)]

    def allocate_execution_slots(
        self,
        context: RuntimeContext,
        count: int,
    ) -> list[WorkerExecutionSlot]:
        worker_ids = self.allocate_worker_ids(context, count)
        result_ids = self.allocate_worker_result_ids(context, count)
        return [
            WorkerExecutionSlot(worker_id=worker_id, result_id=result_id)
            for worker_id, result_id in zip(worker_ids, result_ids, strict=True)
        ]

    def record_execution(
        self,
        *,
        context: RuntimeContext,
        worker_id: str,
        result_id: str,
        task: dict,
        status: str,
        started_at: str,
        ended_at: str,
        model_calls: int,
        tool_calls: int,
        artifact_refs: list[str],
        validation_refs: list[str],
        failure_evidence_refs: list[str],
        summary: str,
        runtime_profile_id: str,
        actor: str,
    ) -> None:
        if context.run_dir is None:
            return
        store = JsonlStore(self.validator)
        delegation_brief = self.delegation_brief(task)
        brief_quality = self.brief_quality(delegation_brief)
        invocation = WorkerInvocation(
            worker_invocation_id=worker_id,
            run_id=context.run_id or "",
            task_id=task["task_id"],
            agent_id=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            runtime_profile_id=runtime_profile_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            summary=f"Execute {task['task_id']} through {runtime_profile_id}.",
            delegation_brief=delegation_brief,
            brief_quality=brief_quality,
            parent_worker_invocation_id=self._runtime_hint(task, "parent_worker_invocation_id"),
            parent_task_id=self._runtime_hint(task, "parent_task_id"),
            worker_kind=self._runtime_hint(task, "worker_kind") or "primary",
            parallel_safety=str(task.get("parallel_safety") or ""),
        )
        result = WorkerResult(
            worker_result_id=result_id,
            worker_invocation_id=worker_id,
            run_id=context.run_id or "",
            task_id=task["task_id"],
            status=self.worker_result_status(status),
            artifact_refs=artifact_refs,
            validation_refs=validation_refs,
            failure_evidence_refs=failure_evidence_refs,
            cost=WorkerCost(model_calls=max(model_calls, 0), tool_calls=tool_calls),
            summary=summary,
            parent_worker_invocation_id=self._runtime_hint(task, "parent_worker_invocation_id"),
            worker_kind=self._runtime_hint(task, "worker_kind") or "primary",
        )
        store.append(context.run_dir / "workers.jsonl", invocation.to_dict(), "worker_invocation")
        store.append(context.run_dir / "worker_results.jsonl", result.to_dict(), "worker_result")
        AgentRunGraphBuilder(self.validator).write(context.run_dir, run_id=context.run_id)
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "worker_recorded",
                actor,
                f"{worker_id} -> {result.status}",
                {
                    "worker_invocation_id": worker_id,
                    "worker_result_id": result_id,
                    "task_id": task["task_id"],
                    "runtime_profile_id": runtime_profile_id,
                    "brief_quality": brief_quality,
                },
            )

    def worker_status(self, task_status: str) -> str:
        if task_status == "done":
            return "succeeded"
        if task_status == "blocked":
            return "failed"
        return "cancelled"

    def worker_result_status(self, worker_status: str) -> str:
        return {
            "succeeded": "succeeded",
            "failed": "failed",
            "denied": "denied",
            "timeout": "timeout",
        }.get(worker_status, "partial")

    def default_runtime_profile_id(self, task: dict) -> str:
        role = str(task.get("role") or "CoderAgent").lower().replace("agent", "")
        return f"runtime-profile-execute-{role or 'coder'}"

    def delegation_brief(self, task: dict) -> dict:
        return {
            "goal": str(task.get("title") or task.get("description") or task["task_id"]),
            "why": str(task.get("description") or task.get("notes") or "Execute the task contract."),
            "known_context": {
                "task_id": task.get("task_id"),
                "acceptance": list(task.get("acceptance") or []),
                "read_scope": list(task.get("read_scope") or []),
            },
            "files_or_commands": {
                "expected_artifacts": list(task.get("expected_artifacts") or []),
                "validation_commands": list(task.get("validation_commands") or []),
            },
            "constraints": {
                "allowed_tools": list(task.get("allowed_tools") or []),
                "parallel_safety": task.get("parallel_safety"),
                "merge_strategy": task.get("merge_strategy"),
            },
            "allowed_writes": list(task.get("write_scope") or task.get("expected_changed_files") or []),
            "expected_output": list(task.get("expected_artifacts") or []),
            "verification_expectation": {
                "policy": task.get("verification_policy") or {},
                "completion_contract": task.get("completion_contract") or {},
            },
        }

    def brief_quality(self, brief: dict) -> dict:
        required = [
            "goal",
            "why",
            "known_context",
            "constraints",
            "allowed_writes",
            "expected_output",
            "verification_expectation",
        ]
        missing = [key for key in required if not brief.get(key)]
        return {
            "status": "pass" if not missing else "warn",
            "missing_fields": missing,
            "required_fields": required,
        }

    def delegation_gate(self, task: dict) -> dict:
        brief = self.delegation_brief(task)
        quality = self.brief_quality(brief)
        risk = self._delegation_risk(task)
        blocking = quality["status"] != "pass" and risk in {"high", "write"}
        return {
            "status": "blocked" if blocking else "pass",
            "risk": risk,
            "reason": (
                "Delegation brief quality gate blocked high-risk worker: "
                + ", ".join(quality["missing_fields"])
                if blocking
                else "Delegation brief quality gate passed."
            ),
            "delegation_brief": brief,
            "brief_quality": quality,
        }

    def _delegation_risk(self, task: dict) -> str:
        raw_risk = str(task.get("risk") or task.get("risk_level") or "").lower()
        if raw_risk == "high":
            return "high"
        risk_score = task.get("risk_score")
        if isinstance(risk_score, int | float) and float(risk_score) >= 0.7:
            return "high"
        if task.get("parallel_safety") == "readonly":
            return "low"
        if (
            str(task.get("task_kind") or "").lower() in {"research", "diagnostic"}
            and not task.get("write_scope")
            and not task.get("expected_changed_files")
        ):
            return "low"
        if self._expects_runtime_scope_request(task):
            return "scope_request"
        allowed_tools = set(task.get("allowed_tools") or [])
        write_tools = {"write_file", "apply_patch", "restore_backup"}
        if allowed_tools & write_tools or task.get("write_scope") or task.get("expected_artifacts"):
            return "write"
        return "low"

    def _expects_runtime_scope_request(self, task: dict) -> bool:
        notes = str(task.get("notes") or "").lower()
        return "require a runtime scope request" in notes or "write_scope was broad" in notes

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _runtime_hint(self, task: dict, key: str) -> str | None:
        hints = task.get("runtime_profile_hints")
        if not isinstance(hints, dict):
            return None
        value = hints.get(key)
        return str(value) if value else None
