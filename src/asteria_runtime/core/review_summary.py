"""Read-only delivery projection: a judgment and execution results are distinct signals."""

from __future__ import annotations

import math
from pathlib import Path

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.core.review_freshness import review_freshness


def _fraction(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def summarize_review(report: dict) -> dict:
    overall = report.get("overall") or {}
    goal = report.get("goal_eval") or {}
    outcome = report.get("outcome_eval") or {}
    score = _fraction(overall.get("score"))
    coverage = _fraction(goal.get("requirement_coverage"))
    return {
        "run_id": report.get("run_id"),
        "status": overall.get("status", "unknown"),
        "reason": str(overall.get("reason") or ""),
        "score": score,
        "score_source": "unassessed"
        if score is None
        else str(overall.get("score_source") or "recorded"),
        "requirement_coverage": coverage,
        "requirement_coverage_source": "unassessed"
        if coverage is None
        else str(goal.get("requirement_coverage_source") or "recorded"),
        "requirement_coverage_runtime_verified": coverage is not None
        and goal.get("requirement_coverage_runtime_verified") is True,
        "verification_pass_rate": _fraction(outcome.get("verification_pass_rate")),
        "verification_scope": "recorded_execution_checks_only",
        "source": "eval_report.json",
    }


def load_review_summary(run_dir: Path, validator: SchemaValidator) -> dict:
    path = run_dir / "eval_report.json"
    if not path.exists():
        return {}
    report = JsonStore(validator).read(path, "eval_report")
    summary = summarize_review(report)
    summary["freshness"] = review_freshness(run_dir.parents[2], run_dir, report, validator)
    summary["effective_status"] = summary["status"] if summary["freshness"]["status"] == "current" else "unknown"
    return summary


def review_detail_lines(review: dict) -> list[str]:
    def value(key: str) -> str:
        number = review.get(key)
        return "unassessed" if number is None else f"{number:.2f}"

    return [
        f"Score: {value('score')}",
        *([f"Current review validity: {review['freshness']['status']} — {review['freshness']['reason']}"] if review.get("freshness") else []),
        f"Reason: {review.get('reason') or 'No review reason recorded.'}",
        f"Score source: {review.get('score_source', 'unassessed')}",
        f"Requirement coverage: {value('requirement_coverage')} "
        f"(source={review.get('requirement_coverage_source', 'unassessed')}; "
        f"runtime_verified={review.get('requirement_coverage_runtime_verified', False)})",
        f"Recorded execution check pass rate: {value('verification_pass_rate')} "
        "(recorded checks only; does not establish requirement coverage)",
    ]
