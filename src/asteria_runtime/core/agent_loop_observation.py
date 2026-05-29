from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import NEXT_ACTIONS
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


OBSERVATION_TYPES = {
    "tool_result",
    "subagent_result",
    "repair_result",
    "replan_result",
    "decision_pending",
    "decision_resolved",
    "stop_report",
}
OBSERVATION_STATUSES = {
    "succeeded",
    "failed",
    "pending",
    "blocked",
    "waiting_user",
    "stopped",
}
_ACTION_TO_OBSERVATION_TYPE = {
    "tool": "tool_result",
    "subagent": "subagent_result",
    "repair": "repair_result",
    "replan": "replan_result",
    "ask": "decision_pending",
    "stop": "stop_report",
}


class AgentLoopObservationError(ValueError):
    pass


def build_agent_loop_observation(
    execution_result: dict[str, Any],
    *,
    sequence: int = 1,
    status: str | None = None,
    summary: str | None = None,
    evidence_refs: list[str] | None = None,
    next_recommended_action: str | None = None,
) -> dict[str, Any]:
    action = str(execution_result.get("action") or "")
    observation_type = _ACTION_TO_OBSERVATION_TYPE.get(action)
    if observation_type is None:
        raise AgentLoopObservationError(f"Unsupported execution action: {action}")
    resolved_status = _observation_status(execution_result, status)
    resolved_next = _next_action(resolved_status, next_recommended_action, action)
    observation = {
        "schema_version": "0.1.0",
        "observation_id": f"agent-loop-observation-{max(1, sequence):04d}",
        "run_id": execution_result.get("run_id"),
        "task_id": str(execution_result.get("task_id") or ""),
        "target_task_id": str(execution_result.get("target_task_id") or ""),
        "created_at": now_iso(),
        "observation_type": observation_type,
        "source_execution_id": str(execution_result.get("execution_id") or ""),
        "source_decision_id": str(execution_result.get("decision_id") or ""),
        "status": resolved_status,
        "summary": summary or _summary_for_execution(execution_result, resolved_status),
        "evidence_refs": _evidence_refs(execution_result, evidence_refs),
        "next_recommended_action": resolved_next,
    }
    validate_agent_loop_observation(observation)
    return observation


def validate_agent_loop_observation(observation: dict[str, Any]) -> None:
    if observation.get("observation_type") not in OBSERVATION_TYPES:
        raise AgentLoopObservationError(
            f"Unsupported observation_type: {observation.get('observation_type')}"
        )
    if observation.get("status") not in OBSERVATION_STATUSES:
        raise AgentLoopObservationError(f"Unsupported status: {observation.get('status')}")
    next_action = observation.get("next_recommended_action")
    if next_action is not None and next_action not in NEXT_ACTIONS:
        raise AgentLoopObservationError(f"Unsupported next_recommended_action: {next_action}")
    for key in (
        "observation_id",
        "task_id",
        "target_task_id",
        "source_execution_id",
        "source_decision_id",
        "summary",
    ):
        if not str(observation.get(key) or "").strip():
            raise AgentLoopObservationError(f"AgentLoopObservation missing {key}")
    if not isinstance(observation.get("evidence_refs"), list):
        raise AgentLoopObservationError("evidence_refs must be an array")


def persist_agent_loop_observation(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    validate_agent_loop_observation(observation)
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        observation,
        "agent_loop_observation",
    )
    return observation


def persist_agent_loop_observation_for_execution(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    execution_result: dict[str, Any] | None,
    status: str | None = None,
    summary: str | None = None,
    evidence_refs: list[str] | None = None,
    next_recommended_action: str | None = None,
) -> dict[str, Any] | None:
    if run_dir is None or not isinstance(execution_result, dict):
        return None
    path = run_dir / "agent_loop_observations.jsonl"
    existing = JsonlStore(validator).read_all(path, "agent_loop_observation")
    observation = build_agent_loop_observation(
        execution_result,
        sequence=len(existing) + 1,
        status=status,
        summary=summary,
        evidence_refs=evidence_refs,
        next_recommended_action=next_recommended_action,
    )
    return persist_agent_loop_observation(
        run_dir=run_dir,
        validator=validator,
        observation=observation,
    )


def latest_agent_loop_observation(
    run_dir: Path | None,
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_observations.jsonl"
    if not path.exists():
        return None
    observations = JsonlStore(validator).read_all(path, "agent_loop_observation")
    return observations[-1] if observations else None


def _observation_status(execution_result: dict[str, Any], status: str | None) -> str:
    if status in OBSERVATION_STATUSES:
        return status
    execution_status = str(execution_result.get("status") or "")
    if execution_status == "waiting_user":
        return "waiting_user"
    if execution_status == "stopped":
        return "stopped"
    worker_status = str(execution_result.get("worker_status") or "")
    if worker_status == "succeeded":
        return "succeeded"
    if worker_status in {"failed", "denied", "timeout"}:
        return "failed"
    if worker_status in {"partial", "queued", "running"}:
        return "pending"
    return "pending"


def _next_action(
    status: str,
    next_recommended_action: str | None,
    action: str,
) -> str | None:
    if next_recommended_action in NEXT_ACTIONS:
        return next_recommended_action
    if status == "failed":
        return "repair"
    if status == "blocked":
        return "ask"
    if status == "waiting_user":
        return "ask"
    if status == "stopped":
        return "stop"
    if action == "subagent":
        return "subagent"
    return None


def _summary_for_execution(execution_result: dict[str, Any], status: str) -> str:
    action = str(execution_result.get("action") or "runtime")
    target = str(execution_result.get("target") or "runtime")
    if action == "subagent":
        worker_id = str(execution_result.get("worker_invocation_id") or "")
        return (
            f"Subagent dispatch observation is {status}"
            + (f" for {worker_id}." if worker_id else ".")
        )
    if action == "ask":
        return "Runtime is waiting for a DecisionPoint response."
    if action == "stop":
        return "Runtime stopped the agent loop and preserved the stop report."
    return f"Runtime action `{action}` reached `{target}` with observation status `{status}`."


def _evidence_refs(
    execution_result: dict[str, Any],
    evidence_refs: list[str] | None,
) -> list[str]:
    refs = [str(item) for item in evidence_refs or [] if item]
    refs.extend(str(item) for item in execution_result.get("evidence_refs") or [] if item)
    for key in (
        "worker_invocation_id",
        "worker_result_id",
        "decision_point_id",
        "decision_point_path",
        "execution_id",
    ):
        value = execution_result.get(key)
        if value:
            refs.append(str(value))
    return list(dict.fromkeys(refs))
