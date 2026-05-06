from __future__ import annotations

from dataclasses import dataclass


TASK_KINDS = {
    "diagnostic",
    "implementation",
    "verification",
    "research",
    "decision",
    "report",
    "ui",
}


@dataclass(frozen=True)
class TaskContractCheck:
    ok: bool
    violations: list[str]
    changed_files: list[str]
    expected_changed_files: list[str]
    verification_total: int
    verification_passed: int

    def summary(self) -> str:
        if self.ok:
            return "Task completion contract satisfied."
        return "Task completion contract violated: " + "; ".join(self.violations)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": self.violations,
            "changed_files": self.changed_files,
            "expected_changed_files": self.expected_changed_files,
            "verification_total": self.verification_total,
            "verification_passed": self.verification_passed,
        }


def task_kind(task: dict) -> str:
    explicit = str(task.get("task_kind") or "").strip().lower()
    if explicit in TASK_KINDS:
        return explicit
    return infer_task_kind(task)


def infer_task_kind(task: dict) -> str:
    text = _task_text(task)
    if any(marker in text for marker in {"decision", "approve", "choose", "select option"}):
        return "decision"
    if any(marker in text for marker in {"research", "investigate", "survey", "source"}):
        return "research"
    if any(marker in text for marker in {"report", "readme", "documentation", "summary"}):
        return "report"
    if any(marker in text for marker in {"ui", "web page", "interface", "dashboard"}):
        return "ui"
    if any(
        marker in text
        for marker in {
            "baseline failure",
            "capture failing",
            "diagnose",
            "failing tests",
            "failures reported",
            "identify failing",
            "identify which tests",
            "locate",
            "run pytest",
            "run tests",
        }
    ):
        return "diagnostic"
    if any(marker in text for marker in {"verify", "verification", "test pass", "tests pass"}):
        return "verification"
    return "implementation"


def completion_contract(task: dict) -> dict:
    contract = task.get("completion_contract")
    if isinstance(contract, dict):
        return contract
    kind = task_kind(task)
    return {
        "requires_changed_artifact": kind in {"implementation", "report", "ui"},
        "requires_verification": kind
        in {"diagnostic", "implementation", "verification", "report", "ui"},
        "allows_expected_failure": kind == "diagnostic",
    }


def requires_changed_artifact(task: dict) -> bool:
    return bool(completion_contract(task).get("requires_changed_artifact", False))


def allows_expected_failure(task: dict) -> bool:
    return bool(completion_contract(task).get("allows_expected_failure", False))


def check_completion_contract(
    task: dict,
    changed_files: list[str],
    verification_results: list,
    allow_verified_noop: bool = False,
) -> TaskContractCheck:
    contract = completion_contract(task)
    expected_files = _expected_changed_files(task)
    normalized_changed = sorted(set(str(item) for item in changed_files if item))
    verification_total = len(verification_results)
    verification_passed = len(
        [result for result in verification_results if getattr(result, "ok", False)]
    )
    verified_noop_allowed = (
        allow_verified_noop
        and verification_total > 0
        and verification_passed == verification_total
        and not normalized_changed
    )
    violations: list[str] = []

    if contract.get("requires_verification") and verification_total == 0:
        violations.append("required verification was not provided")
    if verification_total and verification_passed != verification_total:
        violations.append("verification did not pass")
    if (
        contract.get("requires_changed_artifact")
        and not normalized_changed
        and not verified_noop_allowed
    ):
        violations.append("required changed artifact was not produced")
    if (
        expected_files
        and not verified_noop_allowed
        and not _changed_expected_file(expected_files, normalized_changed)
    ):
        violations.append("expected changed files were not modified: " + ", ".join(expected_files))

    return TaskContractCheck(
        ok=not violations,
        violations=violations,
        changed_files=normalized_changed,
        expected_changed_files=expected_files,
        verification_total=verification_total,
        verification_passed=verification_passed,
    )


def _task_text(task: dict) -> str:
    return " ".join(
        [
            str(task.get("title") or ""),
            str(task.get("description") or ""),
            " ".join(str(item) for item in task.get("acceptance", []) if item),
            " ".join(str(item) for item in task.get("expected_artifacts", []) if item),
        ]
    ).lower()


def _expected_changed_files(task: dict) -> list[str]:
    explicit = task.get("expected_changed_files")
    if not isinstance(explicit, list):
        return []
    generic = {"implementation artifact", "planning artifact", "src/", "tests/"}
    return [str(item) for item in explicit if item and str(item) not in generic]


def _changed_expected_file(expected_files: list[str], changed_files: list[str]) -> bool:
    changed = {_normalize_path(item) for item in changed_files}
    for expected in expected_files:
        normalized = _normalize_path(expected)
        if normalized in changed:
            return True
        if normalized.endswith("/") and any(item.startswith(normalized) for item in changed):
            return True
    return False


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()
