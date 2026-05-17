from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_contract import check_completion_contract
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder


@dataclass(frozen=True)
class TaskAttemptSummary:
    task_id: str
    status: str
    summary: str
    tool_calls: int
    verification_calls: int
    evidence_path: Path | None = None
    validation_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskAttemptRunner:
    evidence_recorder: TaskExecutionEvidenceRecorder
    actor: str = "TaskAttemptRunner"

    def run(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        action: dict,
        create_candidate_workspace: Callable[[RuntimeContext, dict], CandidateWorkspace],
        candidate_context: Callable[[RuntimeContext, CandidateWorkspace], RuntimeContext],
        run_tool_calls: Callable[..., list[Any]],
        record_validation_results: Callable[[RuntimeContext, dict, list[dict], list[Any]], list[str]],
        changed_files: Callable[[list[Any]], list[str]],
        promote_candidate_changes: Callable[[RuntimeContext, CandidateWorkspace, list[str]], list[str]],
        record_experiment: Callable[..., None],
        complete_task_after_candidate_promotion: Callable[[TaskBoard, str, str], None],
        record_task_failure: Callable[..., None],
    ) -> TaskAttemptSummary:
        task_id = task["task_id"]
        candidate = create_candidate_workspace(context, task)
        candidate_context_value = candidate_context(context, candidate)
        self._record_candidate_created(context, task, candidate)
        tool_results = run_tool_calls(action["tool_calls"], task, candidate_context_value)
        task_board.update_status(task_id, "testing")
        verification_results = run_tool_calls(
            action["verification"],
            task,
            candidate_context_value,
            stop_on_failure=False,
            stop_verification_on_fatal=True,
        )
        validation_refs = record_validation_results(
            context,
            task,
            action.get("verification") or [],
            verification_results,
        )
        contract_check = check_completion_contract(
            task,
            changed_files(tool_results),
            verification_results,
        )
        if contract_check.ok:
            merge_gate = MergeGate().evaluate(
                task,
                contract_check.changed_files,
                verification_results,
            )
            contract_with_merge = {**contract_check.to_dict(), "merge_gate": merge_gate.to_dict()}
            if not merge_gate.ok:
                return self._block_for_merge_gate(
                    task=task,
                    task_board=task_board,
                    context=context,
                    action=action,
                    tool_results=tool_results,
                    verification_results=verification_results,
                    validation_refs=validation_refs,
                    contract_with_merge=contract_with_merge,
                    candidate=candidate,
                    merge_gate=merge_gate,
                    record_experiment=record_experiment,
                    record_task_failure=record_task_failure,
                )
            promoted_files = promote_candidate_changes(
                context,
                candidate,
                merge_gate.promotable_files,
            )
            evidence_path = self.evidence_recorder.record(
                context,
                task,
                action,
                tool_results,
                verification_results,
                "done",
                "Verification passed.",
                actor=self.actor,
                contract_check=contract_with_merge,
                candidate_workspace=candidate,
                promoted_files=promoted_files,
            )
            record_experiment(
                context,
                task,
                action,
                tool_results,
                verification_results,
                "keep",
                "Verification passed.",
                contract_check=contract_with_merge,
                candidate_workspace=candidate,
                promoted_files=promoted_files,
            )
            complete_task_after_candidate_promotion(
                task_board,
                task_id,
                action.get("completion_notes") or action["summary"],
            )
            if context.event_logger:
                context.event_logger.record(
                    context.run_id,
                    "task_completed",
                    self.actor,
                    f"Completed {task_id}",
                )
            return TaskAttemptSummary(
                task_id=task_id,
                status="done",
                summary=action["summary"],
                tool_calls=len(action["tool_calls"]),
                verification_calls=len(action["verification"]),
                evidence_path=evidence_path,
                validation_refs=validation_refs,
            )
        return self._block_for_contract(
            task=task,
            task_board=task_board,
            context=context,
            action=action,
            tool_results=tool_results,
            verification_results=verification_results,
            validation_refs=validation_refs,
            contract_check=contract_check,
            candidate=candidate,
            record_experiment=record_experiment,
            record_task_failure=record_task_failure,
        )

    def _block_for_merge_gate(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        action: dict,
        tool_results: list[Any],
        verification_results: list[Any],
        validation_refs: list[str],
        contract_with_merge: dict,
        candidate: CandidateWorkspace,
        merge_gate: Any,
        record_experiment: Callable[..., None],
        record_task_failure: Callable[..., None],
    ) -> TaskAttemptSummary:
        task_id = task["task_id"]
        reason = merge_gate.summary()
        evidence_path = self.evidence_recorder.record(
            context,
            task,
            action,
            tool_results,
            verification_results,
            "blocked",
            reason,
            actor=self.actor,
            contract_check=contract_with_merge,
            candidate_workspace=candidate,
            failure_type="merge_gate",
        )
        record_experiment(
            context,
            task,
            action,
            tool_results,
            verification_results,
            "discard",
            reason,
            contract_check=contract_with_merge,
            candidate_workspace=candidate,
        )
        task_board.update_status(task_id, "blocked")
        task_board.update_notes(task_id, f"{reason}; candidate kept isolated at {candidate.root}.")
        record_task_failure(
            context,
            task,
            "merge_gate",
            reason,
            contract_check=contract_with_merge,
            tool_results=tool_results,
            verification_results=verification_results,
            candidate={
                "summary": action["summary"],
                "changed_files": contract_with_merge.get("changed_files", []),
                "promotable_files": merge_gate.promotable_files,
            },
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "merge_gate_blocked",
                self.actor,
                reason,
                {"task_id": task_id, "violations": merge_gate.violations},
            )
        return TaskAttemptSummary(
            task_id=task_id,
            status="blocked",
            summary=reason,
            tool_calls=len(action["tool_calls"]),
            verification_calls=len(action["verification"]),
            evidence_path=evidence_path,
            validation_refs=validation_refs,
        )

    def _block_for_contract(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        action: dict,
        tool_results: list[Any],
        verification_results: list[Any],
        validation_refs: list[str],
        contract_check: Any,
        candidate: CandidateWorkspace,
        record_experiment: Callable[..., None],
        record_task_failure: Callable[..., None],
    ) -> TaskAttemptSummary:
        task_id = task["task_id"]
        reason = contract_check.summary()
        evidence_path = self.evidence_recorder.record(
            context,
            task,
            action,
            tool_results,
            verification_results,
            "blocked",
            reason,
            actor=self.actor,
            contract_check=contract_check.to_dict(),
            candidate_workspace=candidate,
            failure_type="contract_violation",
        )
        record_experiment(
            context,
            task,
            action,
            tool_results,
            verification_results,
            "discard",
            reason,
            contract_check=contract_check.to_dict(),
            candidate_workspace=candidate,
        )
        task_board.update_status(task_id, "blocked")
        task_board.update_notes(task_id, f"{reason}; candidate kept isolated at {candidate.root}.")
        record_task_failure(
            context,
            task,
            "contract_violation",
            reason,
            contract_check=contract_check.to_dict(),
            tool_results=tool_results,
            verification_results=verification_results,
            candidate={
                "summary": action["summary"],
                "changed_files": contract_check.changed_files,
            },
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_blocked",
                self.actor,
                f"Blocked {task_id}",
            )
        return TaskAttemptSummary(
            task_id=task_id,
            status="blocked",
            summary=reason,
            tool_calls=len(action["tool_calls"]),
            verification_calls=len(action["verification"]),
            evidence_path=evidence_path,
            validation_refs=validation_refs,
        )

    def _record_candidate_created(
        self,
        context: RuntimeContext,
        task: dict,
        candidate: CandidateWorkspace,
    ) -> None:
        if not context.event_logger:
            return
        context.event_logger.record(
            context.run_id,
            "candidate_workspace_created",
            self.actor,
            f"Created candidate workspace for {task['task_id']}",
            {
                "task_id": task["task_id"],
                "candidate_id": candidate.candidate_id,
                "workspace": str(candidate.root),
                "strategy": candidate.strategy,
                "workspace_policy": candidate.workspace_policy,
                "backend_reason": candidate.backend_reason,
                "branch_name": candidate.branch_name,
            },
        )
