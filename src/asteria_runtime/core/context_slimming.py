from __future__ import annotations

from copy import deepcopy
from typing import Any

from asteria_runtime.core.fast_path_policy import FastPathPolicy, classify_fast_path


SLIM_LIMITS = {
    "events": 8,
    "tool_calls": 8,
    "tool_observations": 8,
    "model_calls": 3,
    "model_profiles": 3,
    "task_execution_evidence": 5,
    "worker_results": 5,
    "merge_gate_evidence": 5,
    "runtime_requests": 5,
}


def review_context_policy(review_context: dict[str, Any]) -> dict[str, Any]:
    goal_spec = review_context.get("goal_spec")
    task_plan = review_context.get("task_plan")
    goal_spec = goal_spec if isinstance(goal_spec, dict) else {}
    task_plan = task_plan if isinstance(task_plan, dict) else {}
    fast_path = classify_fast_path(
        str(goal_spec.get("original_goal") or goal_spec.get("normalized_goal") or ""),
        target_files=_review_target_files(goal_spec, task_plan),
        goal_spec=goal_spec,
    )
    return {
        "mode": fast_path.context_mode,
        "fast_path": fast_path.to_dict(),
        "reason": _policy_reason(fast_path),
    }


def slim_review_context(review_context: dict[str, Any]) -> dict[str, Any]:
    policy = review_context_policy(review_context)
    if policy["mode"] != "slim":
        focused = deepcopy(review_context)
        focused["context_policy"] = policy
        return focused

    slimmed = deepcopy(review_context)
    slimmed["context_policy"] = policy
    trajectory = slimmed.get("trajectory")
    if isinstance(trajectory, dict):
        raw_refs: dict[str, Any] = {}
        for key, limit in SLIM_LIMITS.items():
            value = trajectory.get(key)
            if isinstance(value, list):
                raw_refs[key] = _omission_summary(value, limit)
                trajectory[key] = value[-limit:]
        runtime_os = trajectory.get("runtime_os_evidence")
        if isinstance(runtime_os, dict):
            raw_refs["runtime_os_evidence"] = {}
            for key in (
                "task_execution_evidence",
                "worker_results",
                "merge_gate_evidence",
                "runtime_requests",
            ):
                value = runtime_os.get(key)
                if isinstance(value, list):
                    limit = SLIM_LIMITS.get(key, 5)
                    raw_refs["runtime_os_evidence"][key] = _omission_summary(value, limit)
                    runtime_os[key] = value[-limit:]
        trajectory["raw_evidence_refs"] = raw_refs
        trajectory["context_slimmed"] = True
    return slimmed


def _review_target_files(goal_spec: dict[str, Any], task_plan: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for item in goal_spec.get("target_outputs") or []:
        if isinstance(item, str) and item:
            files.append(item)
    for task in task_plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for item in task.get("expected_artifacts") or []:
            if isinstance(item, str) and item:
                files.append(item)
    return list(dict.fromkeys(files))


def _policy_reason(fast_path: FastPathPolicy) -> str:
    if fast_path.context_mode == "slim":
        return "Low-risk fast-path review uses slim context; raw evidence remains in persisted run files."
    return "Focused context keeps more evidence because the task is complex or high risk."


def _omission_summary(value: list[Any], limit: int) -> dict[str, int]:
    total = len(value)
    kept = min(total, limit)
    return {
        "total": total,
        "kept": kept,
        "omitted": max(0, total - kept),
    }
