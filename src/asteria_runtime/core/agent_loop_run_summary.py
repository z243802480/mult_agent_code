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
        "evidence_refs": list(dict.fromkeys(refs)),
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
