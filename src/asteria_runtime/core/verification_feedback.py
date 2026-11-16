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

    return (
        "Observed workspace effects outside the explicit goal edit boundary: "
        + json.dumps({"effects": effects[:16], "omitted_count": max(0, len(effects) - 16)}, ensure_ascii=False)
        + ". These are recorded effects, including effects of failed commands; later green "
        "checks do not resolve them. Stop broadening the probe. Select verification whose inputs "
        "and side effects are bounded by the actual request. Do not delete, move, restore or "
        "otherwise rewrite these paths without authorization. If a concrete command needs consent, "
        "use request_execution_permission with its exact tool_name/args and reason. A request is "
        "not permission, and command approval does not expand the goal edit boundary. Preserve "
        "and disclose the incident and any remaining blocker before finishing. Complete tool "
        "observations remain in runtime evidence; omitted paths are not cleared."
    )
