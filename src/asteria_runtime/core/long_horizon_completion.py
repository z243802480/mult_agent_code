from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.slice_completion_judge import (
    apply_model_judge,
    run_slice_completion_judge,
)
from asteria_runtime.models.base import ModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SLICE_COMPLETION_EVAL_FILENAME = "slice_completion_eval.json"

DEFAULT_SLICE_COMPLETION_POLICY: dict[str, Any] = {
    "requires_accepted_run": True,
    "requires_review_pass": True,
    "requires_all_tasks_done": False,
    "min_review_score": None,
    "enable_model_judge": False,
    "model_judge_tier": "medium",
}


def resolve_slice_completion_policy(north_star: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(DEFAULT_SLICE_COMPLETION_POLICY)
    if not north_star:
        return policy
    raw = north_star.get("slice_completion_policy")
    if not isinstance(raw, dict):
        return policy
    for key in ("requires_accepted_run", "requires_review_pass", "requires_all_tasks_done"):
        if key in raw and isinstance(raw[key], bool):
            policy[key] = raw[key]
    if "min_review_score" in raw:
        value = raw["min_review_score"]
        if value is None:
            policy["min_review_score"] = None
        elif isinstance(value, (int, float)):
            policy["min_review_score"] = float(value)
    if "enable_model_judge" in raw and isinstance(raw["enable_model_judge"], bool):
        policy["enable_model_judge"] = raw["enable_model_judge"]
    if "model_judge_tier" in raw and isinstance(raw["model_judge_tier"], str):
        tier = raw["model_judge_tier"].strip().lower()
        if tier:
            policy["model_judge_tier"] = tier
    return policy


def _load_eval_report(run_dir: Path, validator: SchemaValidator) -> dict[str, Any] | None:
    path = run_dir / "eval_report.json"
    if not path.exists():
        return None
    payload = JsonStore(validator).read(path, "eval_report")
    return payload if isinstance(payload, dict) else None


def _review_score_passes(review_score: Any, min_score: Any) -> bool:
    if min_score is None:
        return True
    if not isinstance(review_score, (int, float)):
        return False
    return float(review_score) >= float(min_score)


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
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    run_dir = root / ".asteria" / "runs" / run_id
    north_star = NorthStarStore(root, validator).read()
    policy = resolve_slice_completion_policy(north_star)
    task_plan = _load_task_plan(run_dir, validator)
    eval_report = _load_eval_report(run_dir, validator)
    overall = eval_report.get("overall") if eval_report else {}
    review_score = overall.get("score") if isinstance(overall, dict) else None
    review_pass = review_status == "pass"
    tasks_done = _tasks_all_done(task_plan)
    min_review_score = policy.get("min_review_score")
    review_score_pass = _review_score_passes(review_score, min_review_score)

    signals = {
        "accepted_run": accepted,
        "review_pass": review_pass,
        "review_score": review_score,
        "review_score_pass": review_score_pass,
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
    if min_review_score is not None:
        checks.append(signals["review_score_pass"])

    slice_complete = all(checks) if checks else accepted and review_pass
    if slice_complete:
        summary = "本 slice 已达成完成契约。"
    elif not accepted:
        summary = "本 slice 未达成：验收未通过。"
    elif not review_pass:
        summary = f"本 slice 未达成：评审状态为 {review_status}。"
    elif min_review_score is not None and not review_score_pass:
        summary = f"本 slice 未达成：评审分数 {review_score} 低于阈值 {min_review_score}。"
    elif policy["requires_all_tasks_done"] and not tasks_done:
        summary = "本 slice 未达成：仍有未完成任务。"
    else:
        summary = "本 slice 未达成完成契约。"

    evaluation = {
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
    judge_result = run_slice_completion_judge(
        run_dir,
        evaluation,
        validator=validator,
        model_client=model_client,
        model_tier=str(policy.get("model_judge_tier") or "medium"),
        north_star_link=north_star_link,
    )
    return apply_model_judge(evaluation, judge_result)


def persist_slice_completion_eval(
    run_dir: Path,
    evaluation: dict[str, Any],
    validator: SchemaValidator,
) -> Path:
    path = run_dir / SLICE_COMPLETION_EVAL_FILENAME
    # No schema contract for the slice-completion eval (HIDE_NOT_DELETE north-star feature);
    # explicit opt-out keeps the skip auditable.
    JsonStore(validator).write(path, evaluation, allow_unvalidated=True)
    return path


def evaluate_and_persist_slice_completion(
    root: Path,
    run_id: str,
    *,
    validator: SchemaValidator,
    accepted: bool,
    review_status: str,
    north_star_link: dict[str, Any] | None = None,
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    run_dir = root / ".asteria" / "runs" / run_id
    evaluation = evaluate_slice_completion(
        root,
        run_id,
        validator=validator,
        accepted=accepted,
        review_status=review_status,
        north_star_link=north_star_link,
        model_client=model_client,
    )
    persist_slice_completion_eval(run_dir, evaluation, validator)
    return evaluation


def latest_slice_completion_eval(root: Path) -> dict[str, Any] | None:
    runs_root = root / ".asteria" / "runs"
    if not runs_root.is_dir():
        return None
    candidates: list[tuple[str, dict[str, Any]]] = []
    for run_dir in runs_root.iterdir():
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
            candidates.append((str(payload.get("evaluated_at") or ""), payload))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
