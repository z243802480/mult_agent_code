from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


PROMOTABLE_PENDING_STATUSES = {
    "queued",
    "pending_manual_approval",
    "approved",
    "blocked",
    "promotion_failed",
}


@dataclass(frozen=True)
class PromotionsResult:
    run_id: str
    action: str
    queue_path: Path
    promotions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "action": self.action,
            "queue_path": str(self.queue_path),
            "promotions": self.promotions,
        }

    def to_text(self) -> str:
        lines = [
            f"Promotion action: {self.action}",
            f"Run: {self.run_id}",
            f"Queue: {self.queue_path}",
        ]
        if not self.promotions:
            lines.append("No candidate promotions.")
            return "\n".join(lines)
        for promotion in self.promotions:
            line = (
                f"- {promotion['promotion_id']} [{promotion['status']}]: "
                f"{promotion['task_id']} candidate={promotion['candidate_id']}"
            )
            files = promotion.get("promoted_files") or promotion.get("promotable_files") or []
            if files:
                line += " files=" + ",".join(files)
            lines.append(line)
            failure = promotion.get("failure")
            if failure:
                lines.append(f"  failure: {failure.get('type')}: {failure.get('message')}")
        return "\n".join(lines)


class PromotionsCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        action: str = "list",
        promotion_id: str | None = None,
        status: str | None = None,
        all_pending: bool = False,
        reason: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.action = action
        self.promotion_id = promotion_id
        self.status = status
        self.all_pending = all_pending
        self.reason = reason or ""
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.queue = CandidatePromotionQueue(self.validator)

    def run(self) -> PromotionsResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `asteria plan` first.")
        run_dir = run_store.run_dir(run_id)
        context = RuntimeContext(
            root=self.root,
            run_id=run_id,
            policy={"protected_paths": []},
            validator=self.validator,
            event_logger=EventLogger(run_dir / "events.jsonl", self.validator),
        )

        if self.action == "list":
            promotions = self._filtered(run_dir)
        elif self.action == "approve":
            promotions = self._approve(context, run_dir)
        elif self.action == "reject":
            promotions = [self._reject(context, run_dir)]
        elif self.action == "retry":
            promotions = [self._promote(context, run_dir, self._require_promotion(run_dir))]
        elif self.action == "discard":
            promotions = [self._discard(context, run_dir)]
        else:
            raise ValueError(f"Unsupported promotion action: {self.action}")
        return PromotionsResult(run_id, self.action, run_dir / "candidate_promotions.jsonl", promotions)

    def _filtered(self, run_dir: Path) -> list[dict]:
        promotions = self.queue.latest_by_promotion(run_dir)
        if not self.status:
            return promotions
        return [item for item in promotions if item.get("status") == self.status]

    def _approve(self, context: RuntimeContext, run_dir: Path) -> list[dict]:
        promotions = self._pending_promotions(run_dir) if self.all_pending else [self._require_promotion(run_dir)]
        approved_or_promoted = []
        for promotion in promotions:
            approved = self.queue.mark_approved(context, promotion)
            approved_or_promoted.append(self._promote(context, run_dir, approved))
        return approved_or_promoted

    def _reject(self, context: RuntimeContext, run_dir: Path) -> dict:
        promotion = self._require_promotion(run_dir)
        return self.queue.mark_rejected(
            context,
            promotion,
            reason=self.reason or "Rejected by operator.",
        )

    def _discard(self, context: RuntimeContext, run_dir: Path) -> dict:
        promotion = self._require_promotion(run_dir)
        candidate = CandidateWorkspace.from_promotion(self.root, run_dir, promotion)
        candidate.discard()
        return self.queue.mark_discarded(
            context,
            promotion,
            reason=self.reason or "Discarded by operator.",
        )

    def _promote(self, context: RuntimeContext, run_dir: Path, promotion: dict) -> dict:
        if str(promotion.get("status")) == "promoted":
            return promotion
        if str(promotion.get("status")) not in PROMOTABLE_PENDING_STATUSES:
            raise ValueError(
                f"promotion is not promotable: {promotion['promotion_id']} "
                f"status={promotion.get('status')}"
            )
        merge_gate = promotion.get("merge_gate") or {}
        if merge_gate.get("ok") is False:
            return self.queue.mark_blocked(
                context,
                promotion,
                {
                    "type": "MergeGateBlocked",
                    "message": str(merge_gate.get("summary") or "Merge gate blocked promotion."),
                    "details": {"merge_gate": merge_gate},
                },
            )
        candidate = CandidateWorkspace.from_promotion(self.root, run_dir, promotion)
        try:
            promoted_files = candidate.promote(list(promotion.get("promotable_files") or []))
        except Exception as exc:
            return self.queue.mark_promotion_failed(
                context,
                promotion,
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "details": {"promotion_id": promotion["promotion_id"]},
                },
            )
        return self.queue.mark_promoted(context, promotion, promoted_files)

    def _pending_promotions(self, run_dir: Path) -> list[dict]:
        promotions = [
            item
            for item in self.queue.latest_by_promotion(run_dir)
            if str(item.get("status")) in PROMOTABLE_PENDING_STATUSES
        ]
        if not promotions:
            raise ValueError("No pending candidate promotions.")
        return promotions

    def _require_promotion(self, run_dir: Path) -> dict:
        if not self.promotion_id:
            raise ValueError("promotion_id is required for this action")
        for promotion in self.queue.latest_by_promotion(run_dir):
            if promotion["promotion_id"] == self.promotion_id:
                return promotion
        raise ValueError(f"promotion not found: {self.promotion_id}")

    def to_json(self, result: PromotionsResult) -> str:
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
