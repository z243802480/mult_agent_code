from __future__ import annotations

from typing import Any


def permission_preview_for_runtime_requests(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a user-semantic permission preview from structured runtime requests."""
    read_scope = _detail_values(requests, "read_scope", "requested_read_scope", "paths")
    write_scope = _detail_values(requests, "write_scope", "requested_write_scope")
    tools = _detail_values(requests, "allowed_tools", "tools", "tool", "tool_name")
    request_types = sorted({str(item.get("request_type") or "") for item in requests if item})
    risk = _highest_risk(requests)

    if write_scope:
        action = "Allow additional workspace changes"
        impact = f"Allow writing {_scope_summary(write_scope)}."
        reversible = "Changes remain reviewable before acceptance."
    elif read_scope:
        action = "Allow additional project context"
        impact = f"Allow reading {_scope_summary(read_scope)}."
        reversible = "Workspace files will not be changed by this approval."
    elif tools:
        action = "Allow an additional tool"
        impact = f"Allow use of {_scope_summary(tools)}."
        reversible = "The tool remains bounded by the current task contract."
    elif "budget_request" in request_types:
        action = "Allow more task budget"
        impact = "Allow the current task to use additional bounded runtime budget."
        reversible = "The task can still be stopped at the next bounded checkpoint."
    elif "model_upgrade_request" in request_types:
        action = "Allow a stronger model route"
        impact = "Allow the current task to use a stronger model route."
        reversible = "The route applies only to the current controlled task."
    else:
        action = "Review a task boundary change"
        impact = "Review the requested task contract change before work continues."
        reversible = "Rejecting keeps the current task boundary unchanged."

    return {
        "action": action,
        "impact": impact,
        "scope": _combined_scope_summary(read_scope, write_scope, tools),
        "network": _network_summary(request_types, tools),
        "risk": risk,
        "reversible": reversible,
        "scope_detail": {
            "read_scope": read_scope,
            "write_scope": write_scope,
            "tools": tools,
            "request_types": request_types,
        },
    }


def _detail_values(requests: list[dict[str, Any]], *keys: str) -> list[str]:
    values: list[str] = []
    for request in requests:
        details = request.get("details")
        payload = details if isinstance(details, dict) else {}
        for key in keys:
            raw = payload.get(key)
            candidates = raw if isinstance(raw, list) else [raw] if raw else []
            for candidate in candidates:
                value = str(candidate).strip()
                if value and value not in values:
                    values.append(value)
    return values


def _highest_risk(requests: list[dict[str, Any]]) -> str:
    rank = {"low": 0, "medium": 1, "high": 2}
    risks = [str(item.get("risk") or "medium").lower() for item in requests]
    return max(risks or ["medium"], key=lambda value: rank.get(value, 1))


def _scope_summary(values: list[str]) -> str:
    visible = values[:3]
    summary = ", ".join(visible)
    if len(values) > len(visible):
        summary += f", and {len(values) - len(visible)} more"
    return summary


def _combined_scope_summary(read_scope: list[str], write_scope: list[str], tools: list[str]) -> str:
    parts = []
    if read_scope:
        parts.append(f"Read: {_scope_summary(read_scope)}")
    if write_scope:
        parts.append(f"Write: {_scope_summary(write_scope)}")
    if tools:
        parts.append(f"Tools: {_scope_summary(tools)}")
    return "; ".join(parts) or "Current task contract"


def _network_summary(request_types: list[str], tools: list[str]) -> str:
    network_terms = {"network", "web", "http", "mcp"}
    if any(any(term in tool.lower() for term in network_terms) for tool in tools):
        return "The requested tool may access an external service."
    if "model_upgrade_request" in request_types:
        return "The model provider will be contacted for the requested route."
    return "No additional network access requested."
