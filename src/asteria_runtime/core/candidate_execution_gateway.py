from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
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
