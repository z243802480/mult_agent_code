from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


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
        )
        store.append(context.run_dir / "workers.jsonl", invocation.to_dict(), "worker_invocation")
        store.append(context.run_dir / "worker_results.jsonl", result.to_dict(), "worker_result")
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

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
