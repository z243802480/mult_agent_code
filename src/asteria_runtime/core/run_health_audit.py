from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _replan_task_count(task_plan: dict[str, Any]) -> int:
    count = 0
    for task in task_plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        replan = task.get("replan")
        if isinstance(replan, dict) and replan.get("source_task_id"):
            count += 1
    return count


def sample_run_health(run_dir: Path) -> dict[str, Any]:
    """Extract run health metrics for Phase 4 run-health gate."""

    run = _read_json(run_dir / "run.json")
    cost = _read_json(run_dir / "cost_report.json")
    task_plan = _read_json(run_dir / "task_plan.json")
    progress_path = run_dir / "user_progress.jsonl"
    progress_bytes = progress_path.stat().st_size if progress_path.exists() else 0
    progress_events = 0
    if progress_path.exists():
        progress_events = len(
            [line for line in progress_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        )
    replan_tasks = _replan_task_count(task_plan)
    repair_attempts = int(cost.get("repair_attempts") or 0)
    if repair_attempts == 0:
        repair_attempts = replan_tasks
    return {
        "run_id": str(run.get("run_id") or run_dir.name),
        "run_status": run.get("status"),
        "current_phase": run.get("current_phase"),
        "user_progress_bytes": progress_bytes,
        "user_progress_events": progress_events,
        "replan_task_count": replan_tasks,
        "repair_attempts": repair_attempts,
        "model_calls": int(cost.get("model_calls") or 0),
    }


def evaluate_run_health(
    sample: dict[str, Any],
    *,
    max_user_progress_bytes: int = 5_000_000,
    max_user_progress_events: int = 2_000,
    max_replan_tasks: int = 8,
    max_repair_attempts: int = 6,
    allowed_terminal_statuses: tuple[str, ...] = ("completed", "running", "reviewed", "paused"),
) -> dict[str, Any]:
    violations: list[str] = []
    progress_bytes = int(sample.get("user_progress_bytes") or 0)
    progress_events = int(sample.get("user_progress_events") or 0)
    replan_tasks = int(sample.get("replan_task_count") or 0)
    repair_attempts = int(sample.get("repair_attempts") or 0)
    run_status = str(sample.get("run_status") or "unknown")

    if progress_bytes > max_user_progress_bytes:
        violations.append(
            f"user_progress_bytes {progress_bytes} exceeds {max_user_progress_bytes}"
        )
    if progress_events > max_user_progress_events:
        violations.append(
            f"user_progress_events {progress_events} exceeds {max_user_progress_events}"
        )
    if replan_tasks > max_replan_tasks:
        violations.append(f"replan_task_count {replan_tasks} exceeds {max_replan_tasks}")
    if repair_attempts > max_repair_attempts:
        violations.append(f"repair_attempts {repair_attempts} exceeds {max_repair_attempts}")
    if run_status == "blocked":
        violations.append("run_status blocked after bounded recovery")

    ok = not violations
    healthy_terminal = run_status in allowed_terminal_statuses or ok
    return {
        "status": "pass" if ok and healthy_terminal else "fail",
        "ok": ok and healthy_terminal,
        "violations": violations,
        "thresholds": {
            "max_user_progress_bytes": max_user_progress_bytes,
            "max_user_progress_events": max_user_progress_events,
            "max_replan_tasks": max_replan_tasks,
            "max_repair_attempts": max_repair_attempts,
        },
        "sample": sample,
    }


def evaluate_run_health_from_manifest(manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    thresholds = manifest.get("thresholds") if isinstance(manifest.get("thresholds"), dict) else {}
    return evaluate_run_health(
        sample_run_health(run_dir),
        max_user_progress_bytes=int(thresholds.get("max_user_progress_bytes") or 5_000_000),
        max_user_progress_events=int(thresholds.get("max_user_progress_events") or 2_000),
        max_replan_tasks=int(thresholds.get("max_replan_tasks") or 8),
        max_repair_attempts=int(thresholds.get("max_repair_attempts") or 6),
    )
