from __future__ import annotations

from dataclasses import dataclass, field

from asteria_runtime.core.task_contract import path_in_write_scope, requires_changed_artifact, task_kind, write_scope


@dataclass(frozen=True)
class MergeGateResult:
    ok: bool
    promotable_files: list[str]
    violations: list[str]
    risky_files: list[str] = field(default_factory=list)
    risk_level: str = "low"

    def summary(self) -> str:
        if self.ok:
            if self.risky_files:
                return f"Merge gate passed; {len(self.risky_files)} change(s) flagged for review."
            return "Merge gate passed."
        return "Merge gate blocked promotion: " + "; ".join(self.violations)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "promotable_files": self.promotable_files,
            "violations": self.violations,
            "risky_files": self.risky_files,
            "risk_level": self.risk_level,
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
        promotable = [] if violations else normalized_changes
        # Annotate (do NOT block on) per-change risk so the promotion layer can route risky
        # changes to manual approval under the supervised 'reviewed_auto' tier. `ok` stays a
        # pure function of write_scope + verification — risk never blocks the gate itself.
        risky = [path for path in promotable if classify_change_risk(task, path)]
        return MergeGateResult(
            ok=not violations,
            promotable_files=promotable,
            violations=violations,
            risky_files=risky,
            risk_level="high" if risky else "low",
        )


_SENSITIVE_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile",
    "jenkinsfile",
}
_SENSITIVE_DIRS = (".github/", ".gitlab/", ".circleci/", "secrets/")
_SENSITIVE_SUBSTRINGS = ("secret", "credential", "id_rsa", ".env")
_SENSITIVE_SUFFIXES = (".lock", ".pem", ".key", ".tf", ".tfvars")


def classify_change_risk(task: dict, path: str) -> bool:
    """Conservative per-change risk: a high-risk task, or a touch to a sensitive path
    (dependency/lock manifests, CI/CD, container/infra, or secret-adjacent files)."""
    if str((task or {}).get("risk") or "").lower() == "high":
        return True
    return _is_sensitive_path(path)


def _is_sensitive_path(path: str) -> bool:
    normalized = _normalize_path(path).lower()
    if not normalized:
        return False
    name = normalized.rsplit("/", 1)[-1]
    if name in _SENSITIVE_NAMES:
        return True
    if any(normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    if any(segment in normalized for segment in _SENSITIVE_DIRS):
        return True
    if any(token in normalized for token in _SENSITIVE_SUBSTRINGS):
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    if name.startswith(".eslintrc") or name.startswith(".prettierrc"):
        return True
    return False


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/")
