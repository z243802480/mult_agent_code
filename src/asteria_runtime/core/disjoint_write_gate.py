from __future__ import annotations

from dataclasses import dataclass, field

from asteria_runtime.core.task_contract import parallel_safety, write_scope


@dataclass(frozen=True)
class DisjointWriteGateResult:
    ok: bool
    allowed_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "allowed_task_ids": self.allowed_task_ids,
            "blocked_task_ids": self.blocked_task_ids,
            "violations": self.violations,
        }


class DisjointWriteGate:
    """Gate disjoint write fanout before true parallel execution."""

    def evaluate(
        self,
        tasks: list[dict],
        *,
        promotions: list[dict] | None = None,
    ) -> DisjointWriteGateResult:
        violations: list[str] = []
        blocked: list[str] = []
        allowed: list[str] = []
        for task in tasks:
            task_id = str(task.get("task_id") or "unknown")
            task_violations = self._task_violations(task)
            if task_violations:
                blocked.append(task_id)
                violations.extend(f"{task_id}: {violation}" for violation in task_violations)
                continue
            allowed.append(task_id)
        for left_index, left in enumerate(tasks):
            for right in tasks[left_index + 1 :]:
                if self.has_write_conflict(left, right):
                    left_id = str(left.get("task_id") or "unknown")
                    right_id = str(right.get("task_id") or "unknown")
                    violations.append(f"{left_id}/{right_id}: write_scope overlaps")
                    blocked.extend([left_id, right_id])
        unresolved = self._unresolved_promotions(promotions or [])
        if unresolved:
            violations.append(
                "promotion recovery unresolved: " + ", ".join(unresolved)
            )
            blocked.extend(allowed)
        blocked_unique = _unique(blocked)
        allowed_unique = [task_id for task_id in _unique(allowed) if task_id not in blocked_unique]
        return DisjointWriteGateResult(
            ok=not violations,
            allowed_task_ids=allowed_unique,
            blocked_task_ids=blocked_unique,
            violations=_unique(violations),
        )

    def allows(self, tasks: list[dict], *, promotions: list[dict] | None = None) -> bool:
        return self.evaluate(tasks, promotions=promotions).ok

    def has_write_conflict(self, left: dict, right: dict) -> bool:
        left_scope = write_scope(left)
        right_scope = write_scope(right)
        return any(
            _scope_overlaps(left_item, right_item)
            for left_item in left_scope
            for right_item in right_scope
        )

    def _task_violations(self, task: dict) -> list[str]:
        violations: list[str] = []
        if parallel_safety(task) != "disjoint_writes":
            violations.append("parallel_safety is not disjoint_writes")
        if not write_scope(task):
            violations.append("write_scope is required")
        contract = task.get("completion_contract")
        contract = contract if isinstance(contract, dict) else {}
        if contract.get("requires_changed_artifact") is not True:
            violations.append("completion_contract.requires_changed_artifact must be true")
        if contract.get("requires_verification") is not True:
            violations.append("completion_contract.requires_verification must be true")
        return violations

    def _unresolved_promotions(self, promotions: list[dict]) -> list[str]:
        unresolved_statuses = {
            "queued",
            "pending_manual_approval",
            "auto_approved",
            "approved",
            "blocked",
            "promotion_failed",
        }
        refs = []
        for promotion in promotions:
            status = str(promotion.get("status") or "")
            recovery_status = str(promotion.get("recovery_status") or "")
            if status in unresolved_statuses or recovery_status == "unresolved":
                refs.append(str(promotion.get("promotion_id") or "unknown"))
        return _unique(refs)


def _scope_overlaps(left: str, right: str) -> bool:
    left_norm = _normalize_scope(left)
    right_norm = _normalize_scope(right)
    return (
        left_norm == right_norm
        or left_norm.startswith(right_norm)
        or right_norm.startswith(left_norm)
    )


def _normalize_scope(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if normalized and not normalized.endswith("/") and "." not in normalized.rsplit("/", 1)[-1]:
        normalized += "/"
    return normalized


def _unique(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique
