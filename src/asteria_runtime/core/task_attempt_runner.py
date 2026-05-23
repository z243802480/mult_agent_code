from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.core.candidate_promotion_queue import PromotionPendingManualApproval
from asteria_runtime.core.agent_harness import (
    append_harness_observations,
    persist_observation_next_action_plan,
    refresh_tool_observation_plan,
)
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_contract import check_completion_contract
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


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
        runtime_context: dict,
        action: dict,
        create_candidate_workspace: Callable[[RuntimeContext, dict], CandidateWorkspace],
        candidate_context: Callable[[RuntimeContext, CandidateWorkspace], RuntimeContext],
        run_tool_calls: Callable[..., list[Any]],
        record_validation_results: Callable[
            [RuntimeContext, dict, list[dict], list[Any]], list[str]
        ],
        changed_files: Callable[[list[Any]], list[str]],
        promote_candidate_changes: Callable[..., list[str]],
        record_experiment: Callable[..., None],
        complete_task_after_candidate_promotion: Callable[[TaskBoard, str, str], None],
        record_task_failure: Callable[..., None],
    ) -> TaskAttemptSummary:
        task_id = task["task_id"]
        candidate = create_candidate_workspace(context, task)
        candidate_context_value = candidate_context(context, candidate)
        self._record_candidate_created(context, task, candidate)
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="message",
            phase="execute",
            status="running",
            title="Candidate workspace created",
            summary=(
                f"Created isolated candidate {candidate.candidate_id} "
                f"with {candidate.strategy} strategy."
            ),
            artifact_refs=[str(candidate.manifest_path)] if candidate.manifest_path else [],
            data={
                "candidate_id": candidate.candidate_id,
                "strategy": candidate.strategy,
                "workspace_policy": candidate.workspace_policy,
                "backend_reason": candidate.backend_reason,
                "branch_name": candidate.branch_name,
            },
        )
        tool_results = run_tool_calls(action["tool_calls"], task, candidate_context_value)
        self._append_harness_observations(
            runtime_context,
            task,
            tool_results,
            context=context,
            stage="tool_calls",
        )
        task_board.update_status(task_id, "testing")
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="message",
            phase="execute",
            status="running",
            title="Verification started",
            summary=f"Running {len(action['verification'])} verification call(s) for {task_id}.",
            data={"verification_count": len(action["verification"])},
        )
        verification_results = run_tool_calls(
            action["verification"],
            task,
            candidate_context_value,
            stop_on_failure=False,
            stop_verification_on_fatal=True,
        )
        self._append_harness_observations(
            runtime_context,
            task,
            verification_results,
            context=context,
            stage="verification",
        )
        validation_refs = record_validation_results(
            context,
            task,
            action.get("verification") or [],
            verification_results,
        )
        verification_passed = len([result for result in verification_results if result.ok])
        self._record_progress(
            context,
            task,
            channel="evidence",
            event_type="evidence",
            phase="review",
            status="completed",
            title="Validation results recorded",
            summary=(
                f"{verification_passed}/{len(verification_results)} verification call(s) passed "
                f"for {task_id}."
            ),
            evidence_refs=self._run_refs(context, "validation_results.jsonl"),
            data={
                "validation_refs": validation_refs,
                "verification_total": len(verification_results),
                "verification_passed": verification_passed,
            },
        )
        contract_check = check_completion_contract(
            task,
            changed_files(tool_results),
            verification_results,
        )
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="message",
            phase="review" if contract_check.ok else "blocked",
            status="completed" if contract_check.ok else "blocked",
            title="Completion contract checked",
            summary=contract_check.summary(),
            data=contract_check.to_dict(),
        )
        if contract_check.ok:
            merge_gate = MergeGate().evaluate(
                task,
                contract_check.changed_files,
                verification_results,
            )
            contract_with_merge = {**contract_check.to_dict(), "merge_gate": merge_gate.to_dict()}
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="review" if merge_gate.ok else "blocked",
                status="completed" if merge_gate.ok else "blocked",
                title="Merge gate evaluated",
                summary=merge_gate.summary(),
                data=merge_gate.to_dict(),
            )
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
            try:
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="message",
                    phase="execute",
                    status="running",
                    title="Promotion started",
                    summary=(
                        f"Promoting {len(merge_gate.promotable_files)} candidate file(s) "
                        f"for {task_id}."
                    ),
                    file_changes=self._file_changes(merge_gate.promotable_files, "modified"),
                    data={"promotable_files": merge_gate.promotable_files},
                )
                promoted_files = promote_candidate_changes(
                    context,
                    candidate,
                    merge_gate.promotable_files,
                    task_id=task_id,
                    merge_gate=merge_gate.to_dict(),
                )
            except PromotionPendingManualApproval as exc:
                return self._block_for_manual_promotion(
                    task=task,
                    task_board=task_board,
                    context=context,
                    action=action,
                    tool_results=tool_results,
                    verification_results=verification_results,
                    validation_refs=validation_refs,
                    contract_with_merge=contract_with_merge,
                    candidate=candidate,
                    promotion=exc.promotion,
                    record_experiment=record_experiment,
                    record_task_failure=record_task_failure,
                )
            self._record_progress(
                context,
                task,
                channel="file",
                event_type="file_modified",
                phase="execute",
                status="completed",
                title="Candidate promoted",
                summary=f"Promoted {len(promoted_files)} file(s) into the workspace.",
                file_changes=self._file_changes(promoted_files, "modified"),
                artifact_refs=promoted_files,
                data={"promoted_files": promoted_files},
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
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="result",
                status="completed",
                title="Task execution evidence recorded",
                summary=f"{task_id} completed with verified evidence.",
                artifact_refs=promoted_files,
                evidence_refs=[str(evidence_path)],
                data={
                    "task_id": task_id,
                    "status": "done",
                    "tool_calls": len(action["tool_calls"]),
                    "verification_calls": len(action["verification"]),
                },
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

    def _block_for_manual_promotion(
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
        promotion: dict,
        record_experiment: Callable[..., None],
        record_task_failure: Callable[..., None],
    ) -> TaskAttemptSummary:
        task_id = task["task_id"]
        promotion_id = str(promotion["promotion_id"])
        reason = (
            f"Verification passed; candidate promotion {promotion_id} is pending manual "
            "approval. Run `asteria promotions approve --promotion-id "
            f"{promotion_id}` or reject/discard it."
        )
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
            promoted_files=[],
            failure_type="pending_manual_approval",
        )
        record_experiment(
            context,
            task,
            action,
            tool_results,
            verification_results,
            "blocked",
            reason,
            contract_check=contract_with_merge,
            candidate_workspace=candidate,
            promoted_files=[],
        )
        task_board.update_status(task_id, "blocked")
        task_board.update_notes(task_id, reason)
        record_task_failure(
            context,
            task,
            "pending_manual_approval",
            reason,
            contract_check=contract_with_merge,
            tool_results=tool_results,
            verification_results=verification_results,
            candidate={
                "summary": action["summary"],
                "changed_files": contract_with_merge.get("changed_files", []),
                "promotable_files": promotion.get("promotable_files", []),
                "promotion_id": promotion_id,
            },
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_pending_manual_promotion",
                self.actor,
                f"{task_id} pending {promotion_id}",
                {"promotion_id": promotion_id, "candidate_id": candidate.candidate_id},
            )
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="decision",
            phase="blocked",
            status="waiting_user",
            title="Promotion waiting for approval",
            summary=reason,
            evidence_refs=[str(evidence_path)],
            file_changes=self._file_changes(promotion.get("promotable_files", []), "modified"),
            data={
                "promotion_id": promotion_id,
                "promotable_files": promotion.get("promotable_files", []),
                "candidate_id": candidate.candidate_id,
            },
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
        self._record_progress(
            context,
            task,
            channel="evidence",
            event_type="evidence",
            phase="blocked",
            status="blocked",
            title="Merge gate blocked promotion",
            summary=reason,
            evidence_refs=[str(evidence_path)],
            file_changes=self._file_changes(contract_with_merge.get("changed_files", []), "modified"),
            data={"merge_gate": merge_gate.to_dict()},
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
        self._record_progress(
            context,
            task,
            channel="evidence",
            event_type="evidence",
            phase="blocked",
            status="blocked",
            title="Completion contract failed",
            summary=reason,
            evidence_refs=[str(evidence_path)],
            file_changes=self._file_changes(contract_check.changed_files, "modified"),
            data=contract_check.to_dict(),
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

    def _progress_logger(self, context: RuntimeContext) -> UserProgressLogger | None:
        if context.run_dir is None:
            return None
        return UserProgressLogger(context.run_dir / "user_progress.jsonl", context.validator)

    def _record_progress(
        self,
        context: RuntimeContext,
        task: dict,
        *,
        channel: str,
        event_type: str,
        phase: str,
        status: str,
        title: str,
        summary: str,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        file_changes: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        logger = self._progress_logger(context)
        if logger is None:
            return
        logger.record(
            run_id=context.run_id,
            channel=channel,
            event_type=event_type,
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            file_changes=file_changes,
            call_chain=[self.actor],
            execution_chain=[str(task.get("task_id", "")), phase],
            data=data,
        )

    def _append_harness_observations(
        self,
        runtime_context: dict,
        task: dict,
        results: list[Any],
        *,
        context: RuntimeContext,
        stage: str,
    ) -> None:
        append_harness_observations(
            runtime_context,
            task_id=task.get("task_id"),
            stage=stage,
            results=results,
        )
        plan = refresh_tool_observation_plan(runtime_context)
        persist_observation_next_action_plan(
            run_dir=context.run_dir,
            validator=context.validator,
            plan=plan,
            run_id=context.run_id,
            task_id=str(task.get("task_id") or ""),
            trigger=f"task_attempt:{stage}",
        )

    def _file_changes(self, paths: list[str], operation: str) -> list[dict[str, Any]]:
        event_type = "file_created" if operation == "created" else "file_modified"
        return [
            {"path": str(path), "operation": operation, "event_type": event_type}
            for path in paths
        ]

    def _run_refs(self, context: RuntimeContext, filename: str) -> list[str]:
        if context.run_dir is None:
            return []
        return [str(context.run_dir / filename)]
