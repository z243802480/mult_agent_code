from __future__ import annotations


TASK_KINDS = {
    "diagnostic",
    "implementation",
    "verification",
    "research",
    "decision",
    "report",
    "ui",
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


def _task_text(task: dict) -> str:
    return " ".join(
        [
            str(task.get("title") or ""),
            str(task.get("description") or ""),
            " ".join(str(item) for item in task.get("acceptance", []) if item),
            " ".join(str(item) for item in task.get("expected_artifacts", []) if item),
        ]
    ).lower()
