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
        require_candidate_promotions: bool = False,
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
        if require_candidate_promotions:
            candidate_result = self._candidate_promotion_violations(tasks, promotions or [])
            violations.extend(candidate_result.violations)
            blocked.extend(candidate_result.blocked_task_ids)
        blocked_unique = _unique(blocked)
        allowed_unique = [task_id for task_id in _unique(allowed) if task_id not in blocked_unique]
        return DisjointWriteGateResult(
            ok=not violations,
            allowed_task_ids=allowed_unique,
            blocked_task_ids=blocked_unique,
            violations=_unique(violations),
        )

    def allows(
        self,
        tasks: list[dict],
        *,
        promotions: list[dict] | None = None,
        require_candidate_promotions: bool = False,
    ) -> bool:
        return self.evaluate(
            tasks,
            promotions=promotions,
            require_candidate_promotions=require_candidate_promotions,
        ).ok

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

    def _candidate_promotion_violations(
        self,
        tasks: list[dict],
        promotions: list[dict],
    ) -> DisjointWriteGateResult:
        blocked: list[str] = []
        violations: list[str] = []
        latest_promotions = self._latest_promotions(promotions)
        for task in tasks:
            task_id = str(task.get("task_id") or "unknown")
            promotion = self._promotion_for_task(task, latest_promotions)
            if promotion is None:
                blocked.append(task_id)
                violations.append(f"{task_id}: candidate promotion evidence is required")
                continue
            task_violations = self._promotion_violations(task, promotion)
            if task_violations:
                blocked.append(task_id)
                violations.extend(f"{task_id}: {violation}" for violation in task_violations)
        return DisjointWriteGateResult(
            ok=not violations,
            blocked_task_ids=_unique(blocked),
            violations=_unique(violations),
        )

    def _promotion_for_task(
        self,
        task: dict,
        latest_promotions: dict[str, dict],
    ) -> dict | None:
        task_refs = {
            str(task.get("task_id") or ""),
            str(task.get("parent_task_id") or ""),
        }
        for ref in task_refs - {""}:
            if ref in latest_promotions:
                return latest_promotions[ref]
        return None

    def _promotion_violations(self, task: dict, promotion: dict) -> list[str]:
        violations: list[str] = []
        if not str(promotion.get("candidate_id") or ""):
            violations.append("candidate_id is required")
        if not str(promotion.get("workspace") or ""):
            violations.append("candidate workspace is required")
        if not str(promotion.get("workspace_policy") or ""):
            violations.append("candidate workspace_policy is required")
        merge_gate = promotion.get("merge_gate")
        merge_gate = merge_gate if isinstance(merge_gate, dict) else {}
        if merge_gate.get("ok") is not True:
            details = [
                str(item)
                for item in merge_gate.get("violations") or []
                if str(item)
            ]
            suffix = f": {', '.join(details)}" if details else ""
            violations.append(f"merge gate must pass{suffix}")
        promotable_files = [str(item) for item in promotion.get("promotable_files") or []]
        if not promotable_files:
            violations.append("promotable_files are required")
        outside_scope = [
            file_path
            for file_path in promotable_files
            if not any(_scope_contains(scope, file_path) for scope in write_scope(task))
        ]
        if outside_scope:
            violations.append(
                "promotable_files outside write_scope: " + ", ".join(outside_scope)
            )
        return violations

    def _latest_promotions(self, promotions: list[dict]) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for promotion in promotions:
            task_id = str(promotion.get("task_id") or "")
            if task_id:
                latest[task_id] = promotion
        return latest


def _scope_overlaps(left: str, right: str) -> bool:
    left_norm = _normalize_scope(left)
    right_norm = _normalize_scope(right)
    return (
        left_norm == right_norm
        or left_norm.startswith(right_norm)
        or right_norm.startswith(left_norm)
    )


def _scope_contains(scope: str, file_path: str) -> bool:
    scope_norm = _normalize_scope(scope)
    file_norm = _normalize_scope(file_path)
    return scope_norm == file_norm or file_norm.startswith(scope_norm)


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
