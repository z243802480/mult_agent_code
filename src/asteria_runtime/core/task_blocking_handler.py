from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard, TaskStateError
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder


@dataclass(frozen=True)
class BlockingResult:
    task_id: str
    status: str
    summary: str
    evidence_path: Path | None = None


@dataclass(frozen=True)
class TaskBlockingHandler:
    evidence_recorder: TaskExecutionEvidenceRecorder
    evidence_sink: ExecutionEvidenceSink
    actor: str = "TaskBlockingHandler"

    def block_for_policy_decision(
        self,
        *,
        context: RuntimeContext,
        task_board: TaskBoard,
        task: dict,
        action: dict,
        decision: dict,
    ) -> BlockingResult:
        task_id = task["task_id"]
        summary = f"Waiting for decision: {decision['decision_id']}"
        task_board.update_status(task_id, "blocked")
        task_board.update_notes(task_id, summary)
        self.evidence_sink.record_task_failure(
            context,
            task,
            "policy_decision",
            summary,
            candidate={"decision_id": decision["decision_id"]},
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_paused_for_decision",
                self.actor,
                f"{task_id} paused for {decision['decision_id']}",
                {"task_id": task_id, "decision_id": decision["decision_id"]},
            )
        evidence_path = self.evidence_recorder.record(
            context,
            task,
            action,
            [],
            [],
            "blocked",
            summary,
            actor=self.actor,
            candidate={"decision_id": decision["decision_id"]},
            failure_type="policy_decision",
        )
        return BlockingResult(
            task_id=task_id, status="blocked", summary=summary, evidence_path=evidence_path
        )

    def block_for_failure(
        self,
        *,
        context: RuntimeContext,
        task_board: TaskBoard,
        task: dict,
        reason: str,
        failure_type: str,
        action: dict | None = None,
    ) -> BlockingResult:
        task_id = task["task_id"]
        self.block_task(task_board, task_id, reason, context)
        self.evidence_sink.record_task_failure(context, task, failure_type, reason)
        evidence_path = self.evidence_recorder.record(
            context,
            task,
            action,
            [],
            [],
            "blocked",
            reason,
            actor=self.actor,
            failure_type=failure_type,
        )
        return BlockingResult(
            task_id=task_id, status="blocked", summary=reason, evidence_path=evidence_path
        )

    def block_task(
        self,
        task_board: TaskBoard,
        task_id: str,
        reason: str,
        context: RuntimeContext,
    ) -> None:
        try:
            current = task_board.get_task(task_id)
            if current["status"] not in {"blocked", "done", "discarded"}:
                task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, reason)
        except TaskStateError:
            pass
        if context.event_logger:
            context.event_logger.record(context.run_id, "task_blocked", self.actor, reason)
