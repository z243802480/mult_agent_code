from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


NEXT_ACTIONS = {"tool", "subagent", "repair", "replan", "ask", "stop"}
RISK_LEVELS = {"low", "medium", "high"}


class AgentLoopDecisionError(ValueError):
    pass


def normalize_agent_loop_decision(
    raw: dict[str, Any],
    *,
    task: dict[str, Any],
    run_id: str | None,
    sequence: int = 1,
) -> dict[str, Any]:
    """Normalize a model loop decision while keeping legacy ExecutionAction compatible."""

    embedded = raw.get("agent_loop_decision")
    source: dict[str, Any] = embedded if isinstance(embedded, dict) else raw
    embedded_next = source.get("next_action")
    next_action: dict[str, Any] = embedded_next if isinstance(embedded_next, dict) else source
    action = str(next_action.get("action") or _infer_action(raw)).strip().lower()
    if action not in NEXT_ACTIONS:
        action = "stop"
    task_id = str(task.get("task_id") or raw.get("task_id") or "")
    target_task_id = str(next_action.get("target_task_id") or task_id)
    capability_ref = _capability_ref(next_action, raw, action)
    reason = str(
        next_action.get("reason")
        or source.get("reason")
        or raw.get("summary")
        or raw.get("completion_notes")
        or f"Continue {target_task_id} with {action}."
    )
    decision = {
        "schema_version": "0.1.0",
        "decision_id": str(
            source.get("decision_id")
            or f"agent-loop-decision-{max(1, sequence):04d}"
        ),
        "run_id": run_id,
        "task_id": task_id,
        "created_at": str(source.get("created_at") or now_iso()),
        "next_action": {
            "action": action,
            "reason": reason,
            "target_task_id": target_task_id,
            "capability_ref": capability_ref,
            "expected_observation": _expected_observation(next_action, raw, action),
            "risk": _risk(next_action, task),
            "budget_hint": _budget_hint(next_action),
            "evidence_refs": _string_list(next_action.get("evidence_refs") or raw.get("evidence_refs")),
        },
    }
    validate_agent_loop_decision(decision)
    return decision


def validate_agent_loop_decision(decision: dict[str, Any]) -> None:
    action = (((decision.get("next_action") or {}).get("action")) or "").strip().lower()
    if action not in NEXT_ACTIONS:
        raise AgentLoopDecisionError(f"Unsupported next action: {action}")
    next_action = decision.get("next_action") or {}
    missing = [
        key
        for key in (
            "reason",
            "target_task_id",
            "capability_ref",
            "expected_observation",
            "risk",
            "budget_hint",
            "evidence_refs",
        )
        if key not in next_action
    ]
    if missing:
        raise AgentLoopDecisionError(
            "AgentLoopDecision next_action missing required field(s): "
            + ", ".join(missing)
        )
    if next_action.get("risk") not in RISK_LEVELS:
        raise AgentLoopDecisionError(f"Unsupported risk: {next_action.get('risk')}")
    capability = next_action.get("capability_ref")
    if not isinstance(capability, dict) or not capability.get("type") or not capability.get("name"):
        raise AgentLoopDecisionError("capability_ref must include type and name")
    if not isinstance(next_action.get("expected_observation"), dict):
        raise AgentLoopDecisionError("expected_observation must be an object")
    if not isinstance(next_action.get("budget_hint"), dict):
        raise AgentLoopDecisionError("budget_hint must be an object")
    if not isinstance(next_action.get("evidence_refs"), list):
        raise AgentLoopDecisionError("evidence_refs must be an array")


def validate_decision_matches_execution_action(
    decision: dict[str, Any],
    action: dict[str, Any],
) -> None:
    next_action = decision.get("next_action") or {}
    kind = next_action.get("action")
    tool_calls = list(action.get("tool_calls") or []) + list(action.get("verification") or [])
    runtime_requests = list(action.get("runtime_requests") or [])
    if kind == "tool" and not tool_calls:
        raise AgentLoopDecisionError("tool next action requires tool_calls or verification")
    if kind == "ask" and not runtime_requests:
        raise AgentLoopDecisionError("ask next action requires runtime_requests")
    if kind in {"repair", "replan"} and tool_calls:
        raise AgentLoopDecisionError(f"{kind} next action should not also execute tool calls")


def persist_agent_loop_decision(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    decision: dict[str, Any],
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_decisions.jsonl"
    JsonlStore(validator).append(path, decision, "agent_loop_decision")
    return decision


def persist_runtime_agent_loop_decision(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    run_id: str | None,
    task_id: str | None,
    action: str,
    reason: str,
    capability_name: str,
    expected_observation: dict[str, Any] | None = None,
    risk: str = "medium",
    evidence_refs: list[str] | None = None,
    budget_hint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record a runtime-owned loop decision when the model cannot return one."""

    if run_dir is None:
        return None
    existing = JsonlStore(validator).read_all(
        run_dir / "agent_loop_decisions.jsonl",
        "agent_loop_decision",
    )
    decision = {
        "schema_version": "0.1.0",
        "decision_id": f"agent-loop-decision-{len(existing) + 1:04d}",
        "run_id": run_id,
        "task_id": task_id or "run",
        "created_at": now_iso(),
        "next_action": {
            "action": action if action in NEXT_ACTIONS else "stop",
            "reason": reason,
            "target_task_id": task_id or "run",
            "capability_ref": {"type": "runtime", "name": capability_name},
            "expected_observation": expected_observation
            or {
                "summary": "Runtime records the failure and routes it to the next recovery command.",
                "success_signal": "A repair, replan, ask, or stop path is persisted for the run.",
            },
            "risk": risk if risk in RISK_LEVELS else "medium",
            "budget_hint": budget_hint or {"model_calls": 1, "tool_budget_units": 0},
            "evidence_refs": evidence_refs or [],
        },
    }
    validate_agent_loop_decision(decision)
    return persist_agent_loop_decision(
        run_dir=run_dir,
        validator=validator,
        decision=decision,
    )


def latest_agent_loop_decision(
    run_dir: Path | None,
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_decisions.jsonl"
    if not path.exists():
        return None
    decisions = JsonlStore(validator).read_all(path, "agent_loop_decision")
    return decisions[-1] if decisions else None


def recommended_command_for_next_action(next_action: dict[str, Any]) -> str | None:
    action = str(next_action.get("action") or "")
    return {
        "tool": "execute",
        "subagent": "execute",
        "repair": "debug",
        "replan": "replan",
        "ask": "decide --list",
        "stop": "status --debug",
    }.get(action)


def _infer_action(raw: dict[str, Any]) -> str:
    if raw.get("runtime_requests"):
        return "ask"
    if raw.get("tool_calls") or raw.get("verification"):
        return "tool"
    return "stop"


def _capability_ref(
    next_action: dict[str, Any],
    raw: dict[str, Any],
    action: str,
) -> dict[str, str]:
    raw_ref = next_action.get("capability_ref")
    if isinstance(raw_ref, dict) and raw_ref.get("type") and raw_ref.get("name"):
        return {"type": str(raw_ref["type"]), "name": str(raw_ref["name"])}
    if action == "tool":
        calls = list(raw.get("tool_calls") or []) + list(raw.get("verification") or [])
        for call in calls:
            if isinstance(call, dict) and call.get("tool_name"):
                return {"type": "tool", "name": str(call["tool_name"])}
    if action == "subagent":
        return {"type": "subagent", "name": "subagent"}
    if action in {"repair", "replan"}:
        return {"type": "runtime", "name": action}
    if action == "ask":
        return {"type": "runtime", "name": "decision_point"}
    return {"type": "runtime", "name": "stop"}


def _expected_observation(
    next_action: dict[str, Any],
    raw: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    raw_expected = next_action.get("expected_observation")
    if isinstance(raw_expected, dict):
        return raw_expected
    summary = str(raw.get("completion_notes") or raw.get("summary") or f"{action} completed")
    return {
        "summary": summary,
        "success_signal": "runtime records a ToolObservation, DecisionPoint, or stop report",
    }


def _risk(next_action: dict[str, Any], task: dict[str, Any]) -> str:
    risk = str(next_action.get("risk") or task.get("risk") or "medium").lower()
    return risk if risk in RISK_LEVELS else "medium"


def _budget_hint(next_action: dict[str, Any]) -> dict[str, Any]:
    raw = next_action.get("budget_hint")
    if isinstance(raw, dict):
        return raw
    return {"model_calls": 1, "tool_budget_units": 1, "context": "bounded"}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]
