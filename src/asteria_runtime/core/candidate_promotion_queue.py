from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Iterable

from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_PROMOTION_QUEUE_LOCK = RLock()


class PromotionPendingManualApproval(RuntimeError):
    def __init__(self, promotion: dict) -> None:
        self.promotion = promotion
        super().__init__(
            "Candidate promotion is pending manual approval: "
            f"{promotion['promotion_id']}. Run `asteria promotions approve "
            f"--promotion-id {promotion['promotion_id']}` or reject/discard it."
        )


@dataclass(frozen=True)
class CandidatePromotionQueue:
    validator: SchemaValidator
    actor: str = "CandidatePromotionQueue"

    def enqueue_auto_approved(
        self,
        context: RuntimeContext,
        *,
        task_id: str,
        candidate: CandidateWorkspace,
        promotable_files: list[str],
        merge_gate: dict,
    ) -> dict:
        if context.run_dir is None:
            raise RuntimeError("Cannot queue candidate promotion without a run directory.")
        queue_path = context.run_dir / "candidate_promotions.jsonl"
        store = JsonlStore(self.validator)
        with _PROMOTION_QUEUE_LOCK:
            existing_count = self._jsonl_count(queue_path)
            promotion = {
                "schema_version": "0.1.0",
                "promotion_id": f"promotion-{existing_count + 1:04d}",
                "run_id": context.run_id,
                "task_id": task_id,
                "candidate_id": candidate.candidate_id,
                "workspace": str(candidate.root),
                "strategy": candidate.strategy,
                "workspace_policy": candidate.workspace_policy,
                "backend_reason": candidate.backend_reason,
                "branch_name": candidate.branch_name,
                "promotable_files": sorted(set(promotable_files)),
                "promoted_files": [],
                "status": "auto_approved",
                "approval_mode": "auto",
                "merge_gate": merge_gate,
                "failure": None,
                "decision": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            store.append(queue_path, promotion, "candidate_promotion")
        self._record_event(context, "candidate_promotion_queued", promotion)
        return promotion

    def enqueue_pending_manual_approval(
        self,
        context: RuntimeContext,
        *,
        task_id: str,
        candidate: CandidateWorkspace,
        promotable_files: list[str],
        merge_gate: dict,
    ) -> dict:
        if context.run_dir is None:
            raise RuntimeError("Cannot queue candidate promotion without a run directory.")
        queue_path = context.run_dir / "candidate_promotions.jsonl"
        store = JsonlStore(self.validator)
        with _PROMOTION_QUEUE_LOCK:
            existing_count = self._jsonl_count(queue_path)
            promotion = {
                "schema_version": "0.1.0",
                "promotion_id": f"promotion-{existing_count + 1:04d}",
                "run_id": context.run_id,
                "task_id": task_id,
                "candidate_id": candidate.candidate_id,
                "workspace": str(candidate.root),
                "strategy": candidate.strategy,
                "workspace_policy": candidate.workspace_policy,
                "backend_reason": candidate.backend_reason,
                "branch_name": candidate.branch_name,
                "promotable_files": sorted(set(promotable_files)),
                "promoted_files": [],
                "status": "pending_manual_approval",
                "approval_mode": "manual",
                "merge_gate": merge_gate,
                "failure": None,
                "decision": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            store.append(queue_path, promotion, "candidate_promotion")
        self._record_event(context, "candidate_promotion_manual_approval_pending", promotion)
        return promotion

    def mark_promoted(
        self,
        context: RuntimeContext,
        promotion: dict,
        promoted_files: list[str],
    ) -> dict:
        if context.run_dir is None:
            raise RuntimeError("Cannot update candidate promotion without a run directory.")
        queue_path = context.run_dir / "candidate_promotions.jsonl"
        store = JsonlStore(self.validator)
        updated = {
            **promotion,
            "promoted_files": sorted(set(promoted_files)),
            "status": "promoted",
            "failure": None,
            "updated_at": now_iso(),
        }
        store.append(queue_path, updated, "candidate_promotion")
        self._record_event(context, "candidate_promotion_promoted", updated)
        return updated

    def mark_approved(self, context: RuntimeContext, promotion: dict, *, actor: str = "cli") -> dict:
        return self._append_update(
            context,
            promotion,
            {
                "status": "approved",
                "approval_mode": "manual",
                "decision": {"actor": actor, "action": "approve", "decided_at": now_iso()},
                "failure": None,
            },
            "candidate_promotion_approved",
        )

    def mark_rejected(
        self,
        context: RuntimeContext,
        promotion: dict,
        *,
        reason: str,
        actor: str = "cli",
    ) -> dict:
        return self._append_update(
            context,
            promotion,
            {
                "status": "rejected",
                "approval_mode": "manual",
                "decision": {
                    "actor": actor,
                    "action": "reject",
                    "reason": reason,
                    "decided_at": now_iso(),
                },
            },
            "candidate_promotion_rejected",
        )

    def mark_blocked(self, context: RuntimeContext, promotion: dict, failure: dict) -> dict:
        return self._append_update(
            context,
            promotion,
            {
                "status": "blocked",
                "failure": self._normalize_failure(failure),
            },
            "candidate_promotion_blocked",
        )

    def mark_promotion_failed(self, context: RuntimeContext, promotion: dict, failure: dict) -> dict:
        return self._append_update(
            context,
            promotion,
            {
                "status": "promotion_failed",
                "failure": self._normalize_failure(failure),
            },
            "candidate_promotion_failed",
        )

    def mark_discarded(self, context: RuntimeContext, promotion: dict, *, reason: str) -> dict:
        return self._append_update(
            context,
            promotion,
            {
                "status": "discarded",
                "decision": {
                    "actor": "cli",
                    "action": "discard",
                    "reason": reason,
                    "decided_at": now_iso(),
                },
            },
            "candidate_promotion_discarded",
        )

    def read_all(self, run_dir: Path) -> list[dict]:
        queue_path = run_dir / "candidate_promotions.jsonl"
        return JsonlStore(self.validator).read_all(queue_path, "candidate_promotion")

    def latest_by_promotion(self, run_dir: Path) -> list[dict]:
        latest: dict[str, dict] = {}
        for item in self.read_all(run_dir):
            latest[str(item["promotion_id"])] = item
        return list(latest.values())

    def summary(self, run_dir: Path) -> dict:
        latest = self.latest_by_promotion(run_dir)
        status_counts: dict[str, int] = {}
        for item in latest:
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "total": len(latest),
            "status_counts": status_counts,
            "pending": self._filter_status(
                latest, {"queued", "pending_manual_approval", "auto_approved", "approved"}
            ),
            "promoted": self._filter_status(latest, {"promoted"}),
            "blocked": self._filter_status(latest, {"blocked", "promotion_failed"}),
        }

    def _filter_status(self, items: Iterable[dict], statuses: set[str]) -> list[dict]:
        return [item for item in items if str(item.get("status")) in statuses]

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _append_update(
        self,
        context: RuntimeContext,
        promotion: dict,
        updates: dict,
        event_type: str,
    ) -> dict:
        if context.run_dir is None:
            raise RuntimeError("Cannot update candidate promotion without a run directory.")
        updated = {
            **promotion,
            **updates,
            "updated_at": now_iso(),
        }
        JsonlStore(self.validator).append(
            context.run_dir / "candidate_promotions.jsonl",
            updated,
            "candidate_promotion",
        )
        self._record_event(context, event_type, updated)
        return updated

    def _normalize_failure(self, failure: dict) -> dict:
        return {
            "type": str(failure.get("type") or "promotion_failed"),
            "message": str(failure.get("message") or ""),
            "details": failure.get("details") or {},
            "failed_at": str(failure.get("failed_at") or now_iso()),
        }

    def _record_event(self, context: RuntimeContext, event_type: str, promotion: dict) -> None:
        if not context.event_logger:
            return
        context.event_logger.record(
            context.run_id,
            event_type,
            self.actor,
            f"{promotion['promotion_id']} -> {promotion['status']}",
            {
                "promotion_id": promotion["promotion_id"],
                "task_id": promotion["task_id"],
                "candidate_id": promotion["candidate_id"],
                "promoted_files": promotion.get("promoted_files", []),
            },
        )
