from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SLICE_COMPLETION_EVAL_FILENAME = "slice_completion_eval.json"

DEFAULT_SLICE_COMPLETION_POLICY: dict[str, bool] = {
    "requires_accepted_run": True,
    "requires_review_pass": True,
    "requires_all_tasks_done": False,
}


def resolve_slice_completion_policy(north_star: dict[str, Any] | None) -> dict[str, bool]:
    policy = dict(DEFAULT_SLICE_COMPLETION_POLICY)
    if not north_star:
        return policy
    raw = north_star.get("slice_completion_policy")
    if not isinstance(raw, dict):
        return policy
    for key in policy:
        if key in raw and isinstance(raw[key], bool):
            policy[key] = raw[key]
    return policy


def _load_task_plan(run_dir: Path, validator: SchemaValidator) -> dict[str, Any] | None:
    path = run_dir / "task_plan.json"
    if not path.exists():
        return None
    payload = JsonStore(validator).read(path, "task_board")
    return payload if isinstance(payload, dict) else None


def _tasks_all_done(task_plan: dict[str, Any] | None) -> bool:
    if not task_plan:
        return False
    tasks = task_plan.get("tasks") or []
    if not tasks:
        return False
    return all(
        str(item.get("status") or "").lower() in {"done", "completed", "skipped"}
        for item in tasks
        if isinstance(item, dict)
    )


def evaluate_slice_completion(
    root: Path,
    run_id: str,
    *,
    validator: SchemaValidator,
    accepted: bool,
    review_status: str,
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = root / ".asteria" / "runs" / run_id
    north_star = NorthStarStore(root, validator).read()
    policy = resolve_slice_completion_policy(north_star)
    task_plan = _load_task_plan(run_dir, validator)
    review_pass = review_status == "pass"
    tasks_done = _tasks_all_done(task_plan)

    signals = {
        "accepted_run": accepted,
        "review_pass": review_pass,
        "tasks_done": tasks_done,
        "north_star_linked": north_star_link is not None,
    }
    checks: list[bool] = []
    if policy["requires_accepted_run"]:
        checks.append(signals["accepted_run"])
    if policy["requires_review_pass"]:
        checks.append(signals["review_pass"])
    if policy["requires_all_tasks_done"]:
        checks.append(signals["tasks_done"])

    slice_complete = all(checks) if checks else accepted and review_pass
    if slice_complete:
        summary = "本 slice 已达成完成契约。"
    elif not accepted:
        summary = "本 slice 未达成：验收未通过。"
    elif not review_pass:
        summary = f"本 slice 未达成：评审状态为 {review_status}。"
    elif policy["requires_all_tasks_done"] and not tasks_done:
        summary = "本 slice 未达成：仍有未完成任务。"
    else:
        summary = "本 slice 未达成完成契约。"

    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "evaluated_at": now_iso(),
        "slice_complete": slice_complete,
        "summary": summary,
        "signals": signals,
        "policy": policy,
        "north_star_milestone_id": (
            north_star_link.get("milestone_id") if north_star_link else None
        ),
    }


def persist_slice_completion_eval(
    run_dir: Path,
    evaluation: dict[str, Any],
    validator: SchemaValidator,
) -> Path:
    path = run_dir / SLICE_COMPLETION_EVAL_FILENAME
    JsonStore(validator).write(path, evaluation, schema_name=None)
    return path


def evaluate_and_persist_slice_completion(
    root: Path,
    run_id: str,
    *,
    validator: SchemaValidator,
    accepted: bool,
    review_status: str,
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = root / ".asteria" / "runs" / run_id
    evaluation = evaluate_slice_completion(
        root,
        run_id,
        validator=validator,
        accepted=accepted,
        review_status=review_status,
        north_star_link=north_star_link,
    )
    persist_slice_completion_eval(run_dir, evaluation, validator)
    return evaluation


def latest_slice_completion_eval(root: Path) -> dict[str, Any] | None:
    runs_root = root / ".asteria" / "runs"
    if not runs_root.is_dir():
        return None
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        path = run_dir / SLICE_COMPLETION_EVAL_FILENAME
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None
