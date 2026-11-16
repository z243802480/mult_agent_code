"""Factual verification feedback; command/repair selection remains model-owned."""

from pathlib import Path

from asteria_runtime.core.edit_boundary import edit_boundary_allows


def boundary_effects(task: dict, observations: tuple | list, root: Path) -> list[dict]:
    boundary = task.get("edit_boundary")
    if not isinstance(boundary, dict) or boundary.get("mode") != "restricted":
        return []
    effects = []
    for obs in observations:
        changes = obs.data.get("workspace_changes")
        if not isinstance(changes, dict):
            continue  # Unknown scans are not evidence of a clean workspace.
        for operation in ("created", "modified", "deleted"):
            for path in changes.get(operation, []):
                if isinstance(path, str) and not edit_boundary_allows(boundary, path, root=root):
                    effects.append({"path": path, "operation": operation,
                                    "tool_name": obs.tool_name,
                                    "tool_call_id": obs.data.get("tool_call_id")})
    return effects


def boundary_feedback(effects: list[dict]) -> str:
    import json

    return json.dumps({"workspace_effect_observations": {
        "effects": effects[:16], "omitted_count": max(0, len(effects) - 16),
        "comparison": "outside_authored_edit_boundary",
        "authorization_assessment": "not_determined_by_path_observation",
        "generated_state_classification": "unassessed",
        "cleanup_permission": "not_granted_by_observation",
        "authority": "unchanged_current_user_request_and_project_guidance",
        "original_observations_retained": True,
    }}, ensure_ascii=False)
