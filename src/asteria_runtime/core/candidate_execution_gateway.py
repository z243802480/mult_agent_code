from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from asteria_runtime.core.candidate_export import CandidateExporter
from asteria_runtime.core.candidate_promotion_queue import (
    CandidatePromotionQueue,
    PromotionPendingManualApproval,
)
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.merge_gate_dry_run import MergeGateDryRunner
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard, TaskStateError


_PROMOTION_APPLY_LOCK = RLock()


@dataclass(frozen=True)
class CandidateExecutionGateway:
    promotion_queue: CandidatePromotionQueue | None = None

    def create_workspace(self, context: RuntimeContext, task: dict) -> CandidateWorkspace:
        if context.run_dir is None:
            raise RuntimeError("Cannot isolate candidate without a run directory.")
        return CandidateWorkspace.create(context.root, context.run_dir, task["task_id"], task=task)

    def candidate_context(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
    ) -> RuntimeContext:
        return RuntimeContext(
            root=candidate.root,
            run_id=context.run_id,
            policy=context.policy,
            validator=context.validator,
            event_logger=context.event_logger,
            budget=context.budget,
            agent_dir_override=context.asteria_dir,
            run_dir_override=context.run_dir,
        )

    def preview_promotion(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        task: dict,
        changed_files: list[str],
        verification_results: list,
        *,
        worker_invocation_id: str | None = None,
    ) -> tuple[dict, dict]:
        """Export candidate bundle and run merge gate dry-run without promoting."""
        export = CandidateExporter(context.validator).export_and_persist(
            context=context,
            candidate=candidate,
            task=task,
            changed_files=changed_files,
            worker_invocation_id=worker_invocation_id,
        )
        task_id = str(task.get("task_id") or export.get("task_id") or "unknown")
        dry_run = MergeGateDryRunner(context.validator).evaluate_and_persist(
            context,
            [task],
            [export],
            {task_id: verification_results},
        )
        return export, dry_run

    def promote_changes(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        changed_files: list[str],
        *,
        task_id: str | None = None,
        merge_gate: dict | None = None,
    ) -> list[str]:
        if not changed_files:
            return []
        promotion_queue = self.promotion_queue or CandidatePromotionQueue(context.validator)
        with _PROMOTION_APPLY_LOCK:
            if _manual_approval_default(context.policy) or _risk_requires_manual_approval(
                context.policy, merge_gate or {}, candidate, changed_files
            ):
                promotion = promotion_queue.enqueue_pending_manual_approval(
                    context,
                    task_id=task_id or "unknown",
                    candidate=candidate,
                    promotable_files=changed_files,
                    merge_gate=merge_gate or {},
                )
                raise PromotionPendingManualApproval(promotion)
            promotion = promotion_queue.enqueue_auto_approved(
                context,
                task_id=task_id or "unknown",
                candidate=candidate,
                promotable_files=changed_files,
                merge_gate=merge_gate or {},
            )
            try:
                self._ensure_merge_gate_allows_promotion(merge_gate or {})
                promoted_files = candidate.promote(changed_files)
            except Exception as exc:
                promotion_queue.mark_promotion_failed(
                    context,
                    promotion,
                    {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                        "details": {"candidate_id": candidate.candidate_id},
                    },
                )
                raise
            promotion_queue.mark_promoted(context, promotion, promoted_files)
            return promoted_files

    def complete_after_promotion(
        self,
        task_board: TaskBoard,
        task_id: str,
        notes: str,
    ) -> None:
        try:
            task_board.complete_task(task_id, notes)
        except TaskStateError as exc:
            if not str(exc).startswith("Task not found:"):
                raise

    def _ensure_merge_gate_allows_promotion(self, merge_gate: dict) -> None:
        if merge_gate and merge_gate.get("ok") is False:
            raise RuntimeError(str(merge_gate.get("summary") or "Merge gate blocked promotion."))


def _manual_approval_default(policy: dict) -> bool:
    promotion = policy.get("promotion") if isinstance(policy, dict) else None
    if not isinstance(promotion, dict):
        return False
    return bool(promotion.get("manual_approval_default"))


def _risk_requires_manual_approval(
    policy: dict,
    merge_gate: dict,
    candidate=None,
    changed_files=None,
) -> bool:
    # Only the supervised 'reviewed_auto' (a.k.a. balanced) tier holds risky changes for approval:
    # 'ask_everything' already gates edits up-front, and 'auto' is full autopilot. The merge gate
    # annotates risky_files (it never blocks on them); we also treat deleting an existing tracked
    # file as risky. Either routes to the existing pending rail — no new control plane (ADR-0014/0015).
    mode = "reviewed_auto"
    if isinstance(policy, dict):
        mode = str(policy.get("permission_mode") or "reviewed_auto").lower()
    if mode not in {"reviewed_auto", "balanced"}:
        return False
    if isinstance(merge_gate, dict) and merge_gate.get("risky_files"):
        return True
    return _deletes_existing_tracked_file(candidate, changed_files or [])


def _deletes_existing_tracked_file(candidate, changed_files) -> bool:
    # A delete = present in the source tree but removed in the candidate. The merge gate only sees
    # paths (no change-type), so this structural check lives here where both trees are available.
    source_root = getattr(candidate, "source_root", None)
    candidate_root = getattr(candidate, "root", None)
    if source_root is None or candidate_root is None:
        return False
    for relative in changed_files:
        rel = str(relative).replace("\\", "/").strip().lstrip("/")
        if not rel:
            continue
        try:
            if (source_root / rel).exists() and not (candidate_root / rel).exists():
                return True
        except (OSError, ValueError):
            continue
    return False
