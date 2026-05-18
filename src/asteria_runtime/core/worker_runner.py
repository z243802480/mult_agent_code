from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder, RuntimeProfileMount
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


ExecuteTask = Callable[[dict], Any]
ArtifactRefs = Callable[[RuntimeContext, str], list[str]]
FailureRefs = Callable[[Any], list[str]]
EvidenceRefs = Callable[[RuntimeContext, str], list[str]]


@dataclass(frozen=True)
class WorkerRunner:
    validator: SchemaValidator
    recorder: WorkerExecutionRecorder
    runtime_profile_builder: RuntimeProfileBuilder
    hook_manager: RuntimeHookManager | None = None
    actor: str = "WorkerRunner"

    def run(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        runtime_context: dict,
        execute_task: ExecuteTask,
        artifact_refs: ArtifactRefs,
        failure_evidence_refs: FailureRefs,
        task_failure_refs: EvidenceRefs,
        decision_refs: EvidenceRefs,
        validation_refs: EvidenceRefs,
        model_call_count: Callable[[Path], int],
        worker_id: str,
        result_id: str,
    ) -> Any:
        started_at = now_iso()
        run_dir = context.run_dir
        model_calls_before = model_call_count(run_dir / "model_calls.jsonl") if run_dir else 0
        self._emit(
            context,
            "before_worker",
            "worker",
            f"Starting worker {worker_id} for {task['task_id']}",
            task=task,
            worker_invocation_id=worker_id,
        )
        try:
            runtime_mount = self.runtime_profile_builder.build_and_record(
                context=context,
                task=task,
                worker_id=worker_id,
                runtime_context=runtime_context,
                artifact_refs=artifact_refs(context, task["task_id"]),
                failure_evidence_refs=task_failure_refs(context, task["task_id"]),
                decision_refs=decision_refs(context, task["task_id"]),
                validation_refs=validation_refs(context, task["task_id"]),
            )
            summary = execute_task(runtime_mount.runtime_context)
        except Exception as exc:
            ended_at = now_iso()
            self.recorder.record_execution(
                context=context,
                worker_id=worker_id,
                result_id=result_id,
                task=task,
                status="failed",
                started_at=started_at,
                ended_at=ended_at,
                model_calls=(
                    model_call_count(run_dir / "model_calls.jsonl") - model_calls_before
                    if run_dir
                    else 0
                ),
                tool_calls=0,
                artifact_refs=[],
                validation_refs=[],
                failure_evidence_refs=[],
                summary=str(exc),
                runtime_profile_id=self._runtime_profile_id(task, locals().get("runtime_mount")),
                actor=self.actor,
            )
            self._emit(
                context,
                "worker_error",
                "worker",
                f"Worker {worker_id} failed for {task['task_id']}: {exc}",
                task=task,
                worker_invocation_id=worker_id,
                data={"error": str(exc), "error_type": exc.__class__.__name__},
            )
            raise
        ended_at = now_iso()
        self.recorder.record_execution(
            context=context,
            worker_id=worker_id,
            result_id=result_id,
            task=task,
            status=self.recorder.worker_status(summary.status),
            started_at=started_at,
            ended_at=ended_at,
            model_calls=(
                model_call_count(run_dir / "model_calls.jsonl") - model_calls_before
                if run_dir
                else 0
            ),
            tool_calls=summary.tool_calls + summary.verification_calls,
            artifact_refs=artifact_refs(context, task["task_id"]),
            validation_refs=summary.validation_refs,
            failure_evidence_refs=failure_evidence_refs(summary),
            summary=summary.summary,
            runtime_profile_id=self._runtime_profile_id(task, runtime_mount),
            actor=self.actor,
        )
        self._emit(
            context,
            "after_worker",
            "worker",
            f"Finished worker {worker_id} for {task['task_id']}",
            task=task,
            worker_invocation_id=worker_id,
            data={
                "status": self.recorder.worker_status(summary.status),
                "summary": summary.summary,
                "tool_calls": summary.tool_calls,
                "verification_calls": summary.verification_calls,
            },
        )
        return summary

    def _runtime_profile_id(self, task: dict, mount: object) -> str:
        if isinstance(mount, RuntimeProfileMount):
            return mount.runtime_profile_id
        return self.recorder.default_runtime_profile_id(task)

    def _emit(
        self,
        context: RuntimeContext,
        hook_name: str,
        phase: str,
        summary: str,
        *,
        task: dict,
        worker_invocation_id: str,
        data: dict | None = None,
    ) -> None:
        if self.hook_manager is None:
            return
        self.hook_manager.emit(
            context,
            hook_name,
            phase,
            self.actor,
            summary,
            task=task,
            worker_invocation_id=worker_invocation_id,
            data=data,
        )
