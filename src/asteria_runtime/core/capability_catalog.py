from __future__ import annotations

from typing import Any

from asteria_runtime.core.agent_tool_surface import model_tool_surface_for_task
from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy


def task_capability_catalog(
    *,
    task: dict[str, Any],
    runtime_tool_names: list[str],
    permission_mode: str = "reviewed_auto",
    skill_catalog: list[dict[str, Any]] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
    allow_shell: bool = False,
) -> dict[str, Any]:
    """Build a model-visible, task-scoped capability selection catalog."""

    task_kind = str(task.get("task_kind") or "implementation")
    intent = str(task.get("intent") or _intent_for_task_kind(task_kind))
    risk = str(task.get("risk") or _risk_for_task(task))
    policy = CapabilityInvocationPolicy()
    tool_surface = model_tool_surface_for_task(
        runtime_tool_names,
        task,
        allow_shell=allow_shell,
    )
    entries: list[dict[str, Any]] = []
    for tool in tool_surface.get("tools", []):
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        internal = str(tool.get("internal_tool") or name)
        decision = policy.for_capability(
            internal,
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
            capability_type="tool",
        )
        task_allowed = bool(tool.get("task_allowed"))
        available = tool.get("status") == "available"
        entries.append(
            _entry(
                capability_type="tool",
                name=name,
                source="model_tool_surface",
                decision=decision,
                visible=available,
                selected=available and task_allowed and decision["decision"] != "deny",
                skipped_reason=None if task_allowed else "not listed in task allowed_tools",
                blocked_reason=None
                if available and decision["decision"] != "deny"
                else "missing backend or denied by policy",
                metadata={"internal_tool": tool.get("internal_tool"), "kind": tool.get("kind")},
            )
        )
    for skill in skill_catalog or []:
        name = str(skill.get("name") or "")
        if not name:
            continue
        decision = policy.for_capability(
            name,
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
            capability_type="skill",
        )
        allowed = name in {str(item) for item in task.get("allowed_skills", [])}
        entries.append(
            _entry(
                capability_type="skill",
                name=name,
                source=str(skill.get("scope") or "workspace"),
                decision=decision,
                visible=True,
                selected=allowed and decision["decision"] != "deny",
                skipped_reason=None if allowed else "not listed in task allowed_skills",
                blocked_reason=None if decision["decision"] != "deny" else decision["reason"],
                metadata={
                    "description": skill.get("description"),
                    "artifact_types": skill.get("artifact_types") or [],
                },
            )
        )
    for server in mcp_servers or []:
        name = str(server.get("name") or "")
        if not name:
            continue
        allowed_mcp = {str(item) for item in task.get("allowed_mcp", [])}
        decision = policy.for_capability(
            name,
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
            capability_type="mcp",
        )
        allowed = name in allowed_mcp
        entries.append(
            _entry(
                capability_type="mcp",
                name=name,
                source="product_mcp_server_catalog",
                decision=decision,
                visible=True,
                selected=allowed and decision["decision"] != "deny",
                skipped_reason=None if allowed else "not listed in task allowed_mcp",
                blocked_reason=None if decision["decision"] != "deny" else decision["reason"],
                metadata={
                    "server": name,
                    "tools": server.get("tools") or [],
                    "workspace_override": server.get("workspace_override") or {},
                },
            )
        )
        for tool in server.get("tools") or []:
            tool_name = str(tool)
            if not tool_name:
                continue
            capability_name = f"{name}/{tool_name}"
            tool_decision = policy.for_capability(
                capability_name,
                intent=intent,
                task_kind=task_kind,
                permission_mode=permission_mode,
                risk=risk,
                capability_type="mcp",
            )
            tool_allowed = name in allowed_mcp or capability_name in allowed_mcp
            entries.append(
                _entry(
                    capability_type="mcp",
                    name=capability_name,
                    source="product_mcp_tool_catalog",
                    decision=tool_decision,
                    visible=True,
                    selected=tool_allowed and tool_decision["decision"] != "deny",
                    skipped_reason=None if tool_allowed else "not listed in task allowed_mcp",
                    blocked_reason=None
                    if tool_decision["decision"] != "deny"
                    else tool_decision["reason"],
                    metadata={
                        "server": name,
                        "tool": tool_name,
                        "workspace_override": server.get("workspace_override") or {},
                    },
                )
            )
    return {
        "schema_version": "0.1.0",
        "task_id": task.get("task_id"),
        "task_kind": task_kind,
        "intent": intent,
        "risk": risk,
        "permission_mode": permission_mode,
        "summary": _summary(entries),
        "entries": entries,
    }


def _entry(
    *,
    capability_type: str,
    name: str,
    source: str,
    decision: dict[str, Any],
    visible: bool,
    selected: bool,
    skipped_reason: str | None,
    blocked_reason: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    state = "selected" if selected else "blocked" if blocked_reason else "skipped"
    return {
        "capability_type": capability_type,
        "name": name,
        "source": source,
        "visible": visible,
        "selection_state": state,
        "policy_decision": decision,
        "selection_reason": _selection_reason(state, decision, skipped_reason, blocked_reason),
        "skipped_reason": skipped_reason,
        "blocked_reason": blocked_reason,
        "metadata": metadata,
    }


def _summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "visible": len([entry for entry in entries if entry["visible"]]),
        "selected": len([entry for entry in entries if entry["selection_state"] == "selected"]),
        "skipped": len([entry for entry in entries if entry["selection_state"] == "skipped"]),
        "blocked": len([entry for entry in entries if entry["selection_state"] == "blocked"]),
    }


def _selection_reason(
    state: str,
    decision: dict[str, Any],
    skipped_reason: str | None,
    blocked_reason: str | None,
) -> str:
    if state == "selected":
        return str(decision.get("reason") or "capability selected by task contract")
    if state == "blocked":
        return blocked_reason or str(decision.get("reason") or "capability blocked")
    return skipped_reason or "capability visible but not selected for this task"


def _intent_for_task_kind(task_kind: str) -> str:
    normalized = task_kind.strip().lower().replace("-", "_")
    if normalized == "research":
        return "research_goal"
    if normalized == "brainstorm":
        return "brainstorm_goal"
    return "implementation_goal"


def _risk_for_task(task: dict[str, Any]) -> str:
    if task.get("risk") in {"low", "medium", "high"}:
        return str(task["risk"])
    if task.get("write_scope") or task.get("expected_changed_files"):
        return "medium"
    if str(task.get("task_kind") or "").lower() == "research":
        return "medium"
    return "low"
