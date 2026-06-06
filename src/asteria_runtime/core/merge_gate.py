from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.task_contract import path_in_write_scope, requires_changed_artifact, task_kind, write_scope


@dataclass(frozen=True)
class MergeGateResult:
    ok: bool
    promotable_files: list[str]
    violations: list[str]

    def summary(self) -> str:
        if self.ok:
            return "Merge gate passed."
        return "Merge gate blocked promotion: " + "; ".join(self.violations)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "promotable_files": self.promotable_files,
            "violations": self.violations,
        }


class MergeGate:
    def evaluate(
        self,
        task: dict,
        changed_files: list[str],
        verification_results: list,
    ) -> MergeGateResult:
        normalized_changes = sorted(set(_normalize_path(path) for path in changed_files if path))
        violations: list[str] = []
        requires_promotion = requires_changed_artifact(task) or bool(write_scope(task))
        if requires_promotion and not normalized_changes:
            violations.append("no changed files were proposed for promotion")
        denied = [
            path
            for path in normalized_changes
            if not path_in_write_scope(path, write_scope(task), kind=task_kind(task))
        ]
        if denied:
            violations.append("changed files outside write_scope: " + ", ".join(denied))
        failed_verification = [
            str(getattr(result, "summary", "verification failed"))
            for result in verification_results
            if not bool(getattr(result, "ok", False))
        ]
        if failed_verification:
            violations.append("verification failed before promotion")
        return MergeGateResult(
            ok=not violations,
            promotable_files=[] if violations else normalized_changes,
            violations=violations,
        )


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/")
