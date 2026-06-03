from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


EXIT_REASONS = {
    "completed",
    "tool_failed",
    "max_rounds",
    "budget_hard_stop",
    "ask",
    "stop",
    "subagent_pending",
    "repair_dispatch",
    "replan_dispatch",
    "no_action",
}
SUMMARY_STATUSES = {"completed", "blocked", "waiting_user", "stopped"}
RECOVERY_ACTIONS = {"repair", "replan", "ask", "stop"}


def build_agent_loop_run_summary(
    *,
    run_id: str | None,
    task_id: str,
    status: str,
    exit_reason: str,
    rounds_completed: int,
    max_rounds: int,
    summary: str,
    recommended_command: str | None,
    latest_decision: dict[str, Any] | None = None,
    latest_execution: dict[str, Any] | None = None,
    latest_observation: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    context_pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = latest_decision if isinstance(latest_decision, dict) else {}
    execution = latest_execution if isinstance(latest_execution, dict) else {}
    observation = latest_observation if isinstance(latest_observation, dict) else {}
    raw_next_action = decision.get("next_action")
    next_action = raw_next_action if isinstance(raw_next_action, dict) else {}
    clean_status = status if status in SUMMARY_STATUSES else "blocked"
    clean_reason = exit_reason if exit_reason in EXIT_REASONS else "no_action"
    refs = [str(item) for item in evidence_refs or [] if item]
    for value in (
        observation.get("observation_id"),
        execution.get("execution_id"),
        decision.get("decision_id"),
    ):
        if value:
            refs.append(str(value))
    recovery_chain = _recovery_chain(
        status=clean_status,
        exit_reason=clean_reason,
        latest_action=str(next_action.get("action") or execution.get("action") or ""),
        observation=observation,
    )
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "task_id": task_id,
        "created_at": now_iso(),
        "status": clean_status,
        "exit_reason": clean_reason,
        "rounds_completed": max(0, int(rounds_completed)),
        "max_rounds": max(1, int(max_rounds)),
        "summary": summary,
        "recommended_command": recommended_command,
        "latest_decision_id": decision.get("decision_id"),
        "latest_execution_id": execution.get("execution_id"),
        "latest_observation_id": observation.get("observation_id"),
        "latest_action": next_action.get("action") or execution.get("action"),
        "budget": _clean_optional_dict(budget),
        "context_pressure": _clean_optional_dict(context_pressure),
        "recovery_chain": recovery_chain,
        "evidence_refs": list(dict.fromkeys(refs)),
    }


def _clean_optional_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recovery_chain(
    *,
    status: str,
    exit_reason: str,
    latest_action: str,
    observation: dict[str, Any],
) -> dict[str, Any]:
    observation_status = str(observation.get("status") or "")
    observation_next = str(observation.get("next_recommended_action") or "")
    required = (
        status in {"blocked", "waiting_user", "stopped"}
        or exit_reason
        in {
            "tool_failed",
            "budget_hard_stop",
            "ask",
            "stop",
            "repair_dispatch",
            "replan_dispatch",
            "no_action",
        }
        or observation_status in {"failed", "blocked", "waiting_user", "stopped"}
    )
    satisfied = not required or latest_action in RECOVERY_ACTIONS or observation_next in RECOVERY_ACTIONS
    if not required:
        reason = "No recovery chain is required for this completed loop state."
    elif satisfied:
        action = latest_action if latest_action in RECOVERY_ACTIONS else observation_next
        reason = f"Loop exit is covered by `{action}` recovery semantics."
    else:
        reason = "Loop exit has no repair/replan/ask/stop recovery action."
    return {
        "required": required,
        "satisfied": satisfied,
        "latest_action": latest_action or None,
        "observation_status": observation_status or None,
        "observation_next_recommended_action": observation_next or None,
        "allowed_actions": sorted(RECOVERY_ACTIONS),
        "reason": reason,
    }


def persist_agent_loop_run_summary(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    summary: dict[str, Any],
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    JsonStore(validator).write(
        run_dir / "agent_loop_run_summary.json",
        summary,
        "agent_loop_run_summary",
    )
    return summary


def latest_agent_loop_run_summary(
    run_dir: Path | None,
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_run_summary.json"
    if not path.exists():
        return None
    return JsonStore(validator).read(path, "agent_loop_run_summary")
