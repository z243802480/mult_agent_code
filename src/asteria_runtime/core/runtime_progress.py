from __future__ import annotations

from typing import Any

from asteria_runtime.core.main_path import canonical_next_command


def build_runtime_progress(
    *,
    workflow_state: str | None,
    main_path: dict | None,
    todo_view: dict | None,
    latest_execution: dict | None = None,
    latest_decision: dict | None = None,
    latest_execution_result: dict | None = None,
    latest_observation: dict | None = None,
    agent_loop_summary: dict | None = None,
    validation_conclusion: dict | None = None,
) -> dict[str, Any]:
    """Collapse user-facing runtime progress into one stable product object."""

    path = main_path or {}
    todo = todo_view or path.get("todo_view") or {}
    validation = validation_conclusion or {}
    loop_summary = agent_loop_summary or {}
    command = canonical_next_command(path, None)
    current_todo = todo.get("current") or {}
    observation = latest_observation or {}
    decision = latest_decision or {}
    execution_result = latest_execution_result or {}
    execution = latest_execution or {}
    return {
        "schema_version": "0.1.0",
        "workflow_state": workflow_state,
        "path": path.get("path") or "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop",
        "active_stage": path.get("active_stage"),
        "current_step": path.get("current_step"),
        "next_command": command,
        "current_blocker": path.get("current_blocker"),
        "permission_boundary": path.get("permission_boundary"),
        "todo": {
            "current": current_todo or None,
            "summary": todo.get("summary"),
            "counts": todo.get("counts") or {},
        },
        "tool_use": _tool_use(execution, execution_result),
        "verification": _verification(validation, todo),
        "loop": {
            "latest_decision": _decision_summary(decision),
            "latest_observation": _observation_summary(observation),
            "exit_reason": loop_summary.get("exit_reason")
            or loop_summary.get("stop_reason"),
            "rounds": loop_summary.get("rounds")
            or loop_summary.get("round_count")
            or loop_summary.get("iteration_count"),
        },
        "evidence_refs": _evidence_refs(path, execution, execution_result, loop_summary),
    }


def _tool_use(execution: dict, execution_result: dict) -> dict[str, Any]:
    target = execution.get("task_id") or execution_result.get("target_task_id")
    status = execution.get("status") or execution_result.get("status")
    summary = execution.get("summary") or execution_result.get("summary")
    return {
        "target_task_id": target,
        "status": status,
        "summary": summary,
        "action": execution_result.get("action") or execution_result.get("target"),
        "worker": execution_result.get("worker_id")
        or execution_result.get("worker_profile")
        or execution_result.get("runtime_profile"),
    }


def _verification(validation: dict, todo_view: dict) -> dict[str, Any]:
    todo_verification = todo_view.get("verification") or {}
    status = validation.get("status") or todo_verification.get("status")
    summary = validation.get("summary") or todo_verification.get("summary")
    return {
        "status": status,
        "summary": summary,
        "passed": validation.get("passed"),
        "failed": validation.get("failed"),
    }


def _decision_summary(decision: dict) -> dict[str, Any]:
    next_action = decision.get("next_action") or {}
    return {
        "action": next_action.get("action"),
        "reason": next_action.get("reason") or decision.get("reason"),
        "target_task_id": next_action.get("target_task_id") or decision.get("target_task_id"),
    }


def _observation_summary(observation: dict) -> dict[str, Any]:
    return {
        "status": observation.get("status"),
        "summary": observation.get("summary"),
        "next_recommended_action": observation.get("next_recommended_action"),
        "requires_follow_up_decision": observation.get("requires_follow_up_decision"),
    }


def _evidence_refs(
    main_path: dict,
    execution: dict,
    execution_result: dict,
    loop_summary: dict,
) -> list[str]:
    refs: list[str] = []
    refs.extend(str(ref) for ref in main_path.get("maintainer_refs") or [] if ref)
    for key in ("evidence_path", "path"):
        value = execution.get(key) or execution_result.get(key)
        if value:
            refs.append(str(value))
    latest_evidence = loop_summary.get("latest_evidence") or {}
    if latest_evidence.get("path"):
        refs.append(str(latest_evidence["path"]))
    return list(dict.fromkeys(refs))[:8]
