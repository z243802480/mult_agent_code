from __future__ import annotations

from typing import Any


STAGE_ORDER = ["plan_todo", "tool_use", "verify", "repair", "ask", "stop"]

STAGE_LABELS = {
    "plan_todo": "Plan/Todo",
    "tool_use": "Tool Use",
    "verify": "Verify",
    "repair": "Repair",
    "ask": "Ask",
    "stop": "Stop",
}


def build_main_path(
    *,
    workflow_state: str | None,
    recommended_next_command: str | None,
    current_blocker: str | None = None,
    context: dict | None = None,
    validation_conclusion: dict | None = None,
) -> dict[str, Any]:
    """Collapse runtime evidence into the user-facing agent loop path."""

    context = context or {}
    validation = validation_conclusion or context.get("validation_conclusion") or {}
    run_status = context.get("run_status") or {}
    task_summary = context.get("task_summary") or {}
    latest_execution = context.get("latest_execution_evidence") or {}
    latest_decision = context.get("latest_agent_loop_decision") or {}
    latest_observation = context.get("latest_agent_loop_observation") or {}
    agent_loop_summary = context.get("agent_loop_run_summary") or {}
    workspace = context.get("workspace_envelope") or {}
    todo_view = context.get("todo_view") or {}
    command = _clean_command(recommended_next_command)
    active_stage = _active_stage(
        workflow_state=workflow_state,
        command=command,
        current_blocker=current_blocker,
        latest_decision=latest_decision,
        latest_observation=latest_observation,
        agent_loop_summary=agent_loop_summary,
        validation=validation,
    )
    stages = [
        _stage(
            "plan_todo",
            _plan_status(run_status, task_summary),
            _plan_summary(run_status, task_summary),
        ),
        _stage(
            "tool_use",
            _tool_status(latest_execution, agent_loop_summary),
            _tool_summary(latest_execution, agent_loop_summary),
        ),
        _stage("verify", _verify_status(validation), _verify_summary(validation)),
        _stage(
            "repair",
            _action_status("repair", active_stage, command, latest_decision),
            _action_summary("repair", command, current_blocker, latest_decision),
        ),
        _stage(
            "ask",
            _action_status("ask", active_stage, command, latest_decision),
            _action_summary("ask", command, current_blocker, latest_decision),
        ),
        _stage(
            "stop",
            _stop_status(workflow_state, active_stage, agent_loop_summary),
            _stop_summary(workflow_state, command, agent_loop_summary),
        ),
    ]
    return {
        "schema_version": "0.1.0",
        "path": "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop",
        "active_stage": active_stage,
        "next_command": command,
        "current_blocker": current_blocker,
        "current_step": _current_step(active_stage, command, current_blocker, stages),
        "permission_boundary": str(workspace.get("permission_mode") or "unknown"),
        "todo_view": todo_view,
        "stages": stages,
        "maintainer_refs": _maintainer_refs(context),
    }


def main_path_text_lines(main_path: dict) -> list[str]:
    if not main_path:
        return []
    lines = [
        "Main path:",
        f"- path: {main_path.get('path') or 'Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop'}",
        f"- active: {STAGE_LABELS.get(str(main_path.get('active_stage')), main_path.get('active_stage') or 'unknown')}",
        f"- current: {main_path.get('current_step') or 'No current step recorded.'}",
    ]
    if main_path.get("next_command"):
        lines.append(f"- next: asteria {main_path['next_command']}")
    if main_path.get("permission_boundary"):
        lines.append(f"- permission: {main_path['permission_boundary']}")
    return lines


def canonical_next_command(main_path: dict, fallback: str | None = None) -> str | None:
    if "next_command" not in main_path:
        return fallback
    command = main_path.get("next_command")
    if command is None:
        return None
    text = str(command).strip()
    return text or None


def _stage(stage_id: str, status: str, summary: str) -> dict[str, str]:
    return {
        "id": stage_id,
        "label": STAGE_LABELS[stage_id],
        "status": status,
        "summary": summary,
    }


def _clean_command(command: str | None) -> str | None:
    if command is None:
        return None
    text = str(command).strip()
    return text or None


def _plan_status(run_status: dict, task_summary: dict) -> str:
    phase = str(run_status.get("current_phase") or "").upper()
    total = int(task_summary.get("total") or 0)
    if phase in {"PLAN", "PLANNING"}:
        return "active"
    if total:
        return "done"
    return "pending"


def _plan_summary(run_status: dict, task_summary: dict) -> str:
    total = int(task_summary.get("total") or 0)
    remaining = int(task_summary.get("remaining") or 0)
    if total:
        return f"{total - remaining}/{total} task(s) completed."
    phase = str(run_status.get("current_phase") or "unknown")
    return f"Run phase is {phase}."


def _tool_status(latest_execution: dict, agent_loop_summary: dict) -> str:
    if latest_execution:
        status = str(latest_execution.get("status") or "")
        if status in {"blocked", "failed"}:
            return "blocked"
        return "done"
    if agent_loop_summary:
        return "done"
    return "pending"


def _tool_summary(latest_execution: dict, agent_loop_summary: dict) -> str:
    if latest_execution:
        return (
            f"{latest_execution.get('task_id') or 'task'} "
            f"{latest_execution.get('status') or 'recorded'}: "
            f"{latest_execution.get('summary') or 'tool evidence recorded'}"
        )
    if agent_loop_summary:
        return (
            f"Agent loop exited with {agent_loop_summary.get('exit_reason') or 'unknown'}."
        )
    return "No tool execution evidence recorded yet."


def _verify_status(validation: dict) -> str:
    status = str(validation.get("status") or "")
    if status == "passed":
        return "done"
    if status == "failed":
        return "blocked"
    if status == "not_recorded":
        return "pending"
    return "pending"


def _verify_summary(validation: dict) -> str:
    return str(validation.get("summary") or "Verification has not run yet.")


def _action_status(
    action: str,
    active_stage: str,
    command: str | None,
    latest_decision: dict,
) -> str:
    if active_stage == action:
        return "active"
    next_action = latest_decision.get("next_action") or {}
    if str(next_action.get("action") or "") == action:
        return "ready"
    if action == "repair" and command in {"debug", "replan"}:
        return "active"
    if action == "ask" and command and command.startswith("decide"):
        return "active"
    return "available"


def _action_summary(
    action: str,
    command: str | None,
    current_blocker: str | None,
    latest_decision: dict,
) -> str:
    next_action = latest_decision.get("next_action") or {}
    if str(next_action.get("action") or "") == action:
        return str(next_action.get("reason") or f"{action} requested by model decision.")
    if action == "repair" and command in {"debug", "replan"}:
        return current_blocker or f"Run {command} to recover the main path."
    if action == "ask" and command and command.startswith("decide"):
        return current_blocker or "User decision is needed before continuing."
    return f"{STAGE_LABELS[action]} is available when the loop needs it."


def _stop_status(workflow_state: str | None, active_stage: str, agent_loop_summary: dict) -> str:
    if workflow_state == "accepted":
        return "done"
    if active_stage == "stop":
        return "active"
    if agent_loop_summary.get("exit_reason") == "stop":
        return "ready"
    return "available"


def _stop_summary(
    workflow_state: str | None,
    command: str | None,
    agent_loop_summary: dict,
) -> str:
    if workflow_state == "accepted":
        return "Result accepted and preserved as durable handoff."
    if agent_loop_summary.get("exit_reason"):
        return (
            f"Loop exit: {agent_loop_summary.get('exit_reason')}; "
            f"next command: {command or agent_loop_summary.get('recommended_command') or 'none'}."
        )
    return "Stop preserves evidence and reports the current result."


def _active_stage(
    *,
    workflow_state: str | None,
    command: str | None,
    current_blocker: str | None,
    latest_decision: dict,
    latest_observation: dict,
    agent_loop_summary: dict,
    validation: dict,
) -> str:
    if workflow_state == "accepted":
        return "stop"
    if command in {"review", "accept"}:
        return "verify"
    if command in {"debug", "replan"}:
        return "repair"
    if command and command.startswith("decide"):
        return "ask"
    next_action = latest_decision.get("next_action") or {}
    action = str(next_action.get("action") or "")
    if action in {"tool", "subagent"}:
        return "tool_use"
    if action in {"repair", "replan"}:
        return "repair"
    if action == "ask":
        return "ask"
    if action == "stop":
        return "stop"
    observation_action = str(latest_observation.get("next_recommended_action") or "")
    if observation_action in {"repair", "replan"}:
        return "repair"
    if observation_action == "ask":
        return "ask"
    if agent_loop_summary.get("exit_reason") in {"stop", "max_rounds", "budget_hard_stop"}:
        return "stop"
    if str(validation.get("status") or "") in {"passed", "failed"}:
        return "verify"
    if current_blocker:
        return "repair"
    return "plan_todo"


def _current_step(
    active_stage: str,
    command: str | None,
    current_blocker: str | None,
    stages: list[dict[str, str]],
) -> str:
    if command:
        return f"Run `asteria {command}`."
    if current_blocker:
        return current_blocker
    for stage in stages:
        if stage["id"] == active_stage:
            return stage["summary"]
    return "Continue the main path."


def _maintainer_refs(context: dict) -> list[str]:
    refs: list[str] = []
    for key in (
        "run_loop_summary_path",
        "final_report_summary_path",
        "model_route_timeline_path",
    ):
        value = context.get(key)
        if value:
            refs.append(str(value))
    latest = context.get("latest_execution_evidence") or {}
    if latest.get("evidence_path"):
        refs.append(str(latest["evidence_path"]))
    return list(dict.fromkeys(refs))[:8]
