from __future__ import annotations

from copy import deepcopy
from typing import Any

from asteria_runtime.core.agent_harness import _model_facing_payload
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


def project_review_evidence(review_context: dict[str, Any]) -> dict[str, Any]:
    """Remove only provably redundant observation renderings from the model request.

    All rows, flags, structured output and unique payloads survive, including failures.
    The original context remains the input to deterministic review and normalization;
    persisted ledgers are untouched. This also applies to focused/high-risk reviews.
    """
    projected = deepcopy(review_context)
    removed = {"row_summaries": 0, "commands": 0, "rendered_payloads": 0}
    trajectory = projected.get("trajectory")
    groups = [projected.get("tool_observations")]
    if isinstance(trajectory, dict):
        groups.append(trajectory.get("tool_observations"))
    for rows in groups:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            observation = row.get("observation")
            if not isinstance(observation, dict):
                continue
            if isinstance(row.get("summary"), str) and row["summary"] == observation.get("summary"):
                del row["summary"]
                removed["row_summaries"] += 1
            data = observation.get("data")
            if not isinstance(data, dict):
                continue
            payload = observation.get("payload")
            if isinstance(payload, str) and payload:
                try:
                    rendered = _model_facing_payload(str(observation.get("tool_name") or ""), data)
                except (TypeError, ValueError):
                    rendered = None  # Unusual legacy data must keep its unique evidence.
                if payload == rendered:
                    del observation["payload"]
                    removed["rendered_payloads"] += 1
            command = data.get("command")
            if isinstance(command, str) and command == data.get("requested_command"):
                del data["command"]
                removed["commands"] += 1
    if any(removed.values()):
        projected["review_evidence_projection"] = {
            "removed_duplicate_fields": removed,
            "interpretation": (
                "All observation rows, errors and structured data are retained. "
                "A row summary is omitted only when identical to observation.summary; "
                "data.command only when identical to data.requested_command; payload only "
                "when it is exactly a rendering of the retained observation.data. "
                "Unique payloads (including file contents absent from data) are retained. "
                "Original persisted evidence is unchanged."
            ),
        }
    return projected


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
