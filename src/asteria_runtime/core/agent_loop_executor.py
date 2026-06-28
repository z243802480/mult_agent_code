from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import (
    recommended_command_for_next_action,
    validate_agent_loop_decision,
)
from asteria_runtime.core.subagent_planner import persist_subagent_child_plan
from asteria_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_ACTION_TARGETS = {
    "tool": "tool_gateway",
    "subagent": "subagent_dispatcher",
    "repair": "debug_agent",
    "replan": "replan_command",
    "ask": "decision_point",
    "stop": "stop_report",
}

_ACTION_STATUSES = {
    "tool": "dispatched",
    "subagent": "dispatched",
    "repair": "dispatched",
    "replan": "dispatched",
    "ask": "waiting_user",
    "stop": "stopped",
}


def build_agent_loop_execution_result(
    decision: dict[str, Any],
    *,
    sequence: int = 1,
) -> dict[str, Any]:
    validate_agent_loop_decision(decision)
    next_action = decision["next_action"]
    action = str(next_action["action"])
    if action == "subagent":
        _validate_subagent_decision(decision)
    recommended_command = recommended_command_for_next_action(next_action)
    return {
        "schema_version": "0.1.0",
        "execution_id": f"agent-loop-execution-{max(1, sequence):04d}",
        "decision_id": str(decision["decision_id"]),
        "run_id": decision.get("run_id"),
        "task_id": str(decision["task_id"]),
        "target_task_id": str(next_action["target_task_id"]),
        "created_at": now_iso(),
        "action": action,
        "status": _ACTION_STATUSES[action],
        "target": _ACTION_TARGETS[action],
        "recommended_command": recommended_command,
        "capability_ref": dict(next_action["capability_ref"]),
        "reason": str(next_action["reason"]),
        "expected_observation": dict(next_action["expected_observation"]),
        "risk": str(next_action["risk"]),
        "budget_hint": dict(next_action["budget_hint"]),
        "evidence_refs": list(next_action["evidence_refs"]),
    }


def persist_agent_loop_execution_result(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    decision: dict[str, Any],
    create_decision_point: bool = False,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_execution_results.jsonl"
    existing = JsonlStore(validator).read_all(path, "agent_loop_execution_result")
    result = build_agent_loop_execution_result(decision, sequence=len(existing) + 1)
    linked_decision = None
    if create_decision_point and result["action"] == "ask":
        linked_decision = _ensure_decision_point(run_dir, validator, decision)
    if linked_decision:
        result["decision_point_id"] = linked_decision["decision_id"]
        result["decision_point_path"] = str(run_dir / "decisions.jsonl")
    if result["action"] == "subagent":
        worker = _record_subagent_dispatch(run_dir, validator, decision, result)
        result["worker_invocation_id"] = worker["worker_invocation_id"]
        result["worker_result_id"] = worker["worker_result_id"]
        result["runtime_profile_id"] = worker["runtime_profile_id"]
        result["worker_status"] = worker["worker_status"]
    JsonlStore(validator).append(path, result, "agent_loop_execution_result")
    return result


def persist_subagent_child_plan_for_execution(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    decision: dict[str, Any],
    execution_result: dict[str, Any],
    task: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if run_dir is None or execution_result.get("action") != "subagent":
        return None
    plan = persist_subagent_child_plan(
        run_dir=run_dir,
        validator=validator,
        decision=decision,
        execution_result=execution_result,
        task=task,
        policy=policy,
    )
    if isinstance(plan, dict):
        _record_subagent_child_plan_ref(
            run_dir,
            validator,
            worker_id=str(execution_result.get("worker_invocation_id") or ""),
            child_plan_id=str(plan.get("subagent_child_plan_id") or ""),
        )
    return plan


def complete_subagent_worker_execution(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    execution_result: dict[str, Any],
    status: str,
    summary: str,
    artifact_refs: list[str] | None = None,
    validation_refs: list[str] | None = None,
    failure_evidence_refs: list[str] | None = None,
    child_plan_refs: list[str] | None = None,
    model_calls: int = 0,
    tool_calls: int = 0,
) -> dict[str, Any] | None:
    if run_dir is None or execution_result.get("action") != "subagent":
        return None
    if status not in {"succeeded", "failed", "denied", "timeout"}:
        raise ValueError("subagent worker completion status must be succeeded, failed, denied, or timeout")
    worker_id = str(execution_result.get("worker_invocation_id") or "")
    worker_result_id = str(execution_result.get("worker_result_id") or "")
    runtime_profile_id = str(execution_result.get("runtime_profile_id") or "")
    if not worker_id or not worker_result_id or not runtime_profile_id:
        raise ValueError("subagent execution result is missing worker evidence ids")
    timestamp = now_iso()
    worker = _latest_worker_invocation(run_dir, validator, worker_id)
    result = WorkerResult(
        worker_result_id=worker_result_id,
        worker_invocation_id=worker_id,
        run_id=str(execution_result.get("run_id") or ""),
        task_id=str(execution_result.get("target_task_id") or execution_result.get("task_id") or ""),
        status=status,
        artifact_refs=list(artifact_refs or []),
        validation_refs=list(validation_refs or []),
        failure_evidence_refs=list(failure_evidence_refs or []),
        cost=WorkerCost(model_calls=max(model_calls, 0), tool_calls=max(tool_calls, 0)),
        summary=summary,
        parent_worker_invocation_id=(worker or {}).get("parent_worker_invocation_id"),
        worker_kind=(worker or {}).get("worker_kind") or "subagent",
        child_plan_refs=list(child_plan_refs or (worker or {}).get("child_plan_refs") or []),
    )
    worker_update = WorkerInvocation(
        worker_invocation_id=worker_id,
        run_id=str(execution_result.get("run_id") or ""),
        task_id=str(execution_result.get("target_task_id") or execution_result.get("task_id") or ""),
        agent_id=str((execution_result.get("capability_ref") or {}).get("name") or "subagent"),
        runtime_profile_id=runtime_profile_id,
        status=status,
        started_at=str((worker or {}).get("started_at") or execution_result.get("created_at") or timestamp),
        ended_at=timestamp,
        summary=summary,
        delegation_brief=(worker or {}).get("delegation_brief"),
        brief_quality=(worker or {}).get("brief_quality"),
        parent_worker_invocation_id=(worker or {}).get("parent_worker_invocation_id"),
        parent_task_id=(worker or {}).get("parent_task_id"),
        worker_kind=(worker or {}).get("worker_kind") or "subagent",
        parallel_safety=(worker or {}).get("parallel_safety"),
        child_plan_refs=list(child_plan_refs or (worker or {}).get("child_plan_refs") or []),
    )
    store = JsonlStore(validator)
    store.append(run_dir / "workers.jsonl", worker_update.to_dict(), "worker_invocation")
    store.append(run_dir / "worker_results.jsonl", result.to_dict(), "worker_result")
    return result.to_dict()


def subagent_worker_observation_payload(
    execution_result: dict[str, Any],
    worker_result: dict[str, Any],
) -> dict[str, Any]:
    status = str(worker_result.get("status") or "partial")
    if status == "succeeded":
        observation_status = "succeeded"
        next_action = "stop"
    elif status in {"failed", "denied", "timeout"}:
        observation_status = "failed"
        next_action = "repair"
    else:
        observation_status = "pending"
        next_action = "subagent"
    refs = [
        str(worker_result.get("worker_invocation_id") or ""),
        str(worker_result.get("worker_result_id") or ""),
        *[str(item) for item in worker_result.get("child_plan_refs") or []],
        *[str(item) for item in worker_result.get("artifact_refs") or []],
        *[str(item) for item in worker_result.get("validation_refs") or []],
        *[str(item) for item in worker_result.get("failure_evidence_refs") or []],
    ]
    return {
        "status": observation_status,
        "summary": str(worker_result.get("summary") or "Subagent worker produced no summary."),
        "evidence_refs": [item for item in dict.fromkeys(refs) if item],
        "next_recommended_action": next_action,
        "worker_status": status,
        "worker_invocation_id": str(execution_result.get("worker_invocation_id") or ""),
        "worker_result_id": str(execution_result.get("worker_result_id") or ""),
    }


def latest_agent_loop_execution_result(
    run_dir: Path | None,
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "agent_loop_execution_results.jsonl"
    if not path.exists():
        return None
    results = JsonlStore(validator).read_all(path, "agent_loop_execution_result")
    return results[-1] if results else None


def _ensure_decision_point(
    run_dir: Path,
    validator: SchemaValidator,
    decision: dict[str, Any],
) -> dict[str, Any] | None:
    decisions_path = run_dir / "decisions.jsonl"
    store = JsonlStore(validator)
    existing = store.read_all(decisions_path, "decision_point") if decisions_path.exists() else []
    decision_id = str(decision.get("decision_id") or "")
    for item in existing:
        metadata = item.get("metadata") if isinstance(item, dict) else {}
        if isinstance(metadata, dict) and metadata.get("agent_loop_decision_id") == decision_id:
            return item
    item = _decision_point_from_loop_decision(
        decision,
        sequence=len(existing) + 1,
    )
    validator.validate("decision_point", item)
    store.append(decisions_path, item, "decision_point")
    return item


def _record_subagent_dispatch(
    run_dir: Path,
    validator: SchemaValidator,
    decision: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, str]:
    next_action = decision["next_action"]
    workers_path = run_dir / "workers.jsonl"
    worker_results_path = run_dir / "worker_results.jsonl"
    store = JsonlStore(validator)
    worker_id = _subagent_worker_id(workers_path, decision)
    worker_result_id = _subagent_worker_result_id(worker_results_path, decision)
    capability = next_action["capability_ref"]
    expected = next_action.get("expected_observation")
    expected_observation = expected if isinstance(expected, dict) else {}
    runtime_profile_id = _subagent_runtime_profile_id(capability, worker_id)
    timestamp = str(result.get("created_at") or now_iso())
    task_id = str(next_action["target_task_id"])
    run_id = str(decision.get("run_id") or "")
    worker = WorkerInvocation(
        worker_invocation_id=worker_id,
        run_id=run_id,
        task_id=task_id,
        agent_id=str(capability["name"]),
        runtime_profile_id=runtime_profile_id,
        status="queued",
        started_at=timestamp,
        ended_at=None,
        summary=f"Dispatch {task_id} to subagent {capability['name']}.",
        delegation_brief=_subagent_delegation_brief(decision),
        brief_quality={
            "status": "pass",
            "missing_fields": [],
            "required_fields": [
                "goal",
                "why",
                "known_context",
                "constraints",
                "expected_output",
                "verification_expectation",
            ],
        },
        parent_task_id=str(decision.get("task_id") or ""),
        parent_worker_invocation_id=str(decision.get("parent_worker_invocation_id") or "") or None,
        worker_kind="subagent",
        parallel_safety=str(expected_observation.get("parallel_safety") or "serial"),
    )
    worker_result = WorkerResult(
        worker_result_id=worker_result_id,
        worker_invocation_id=worker_id,
        run_id=run_id,
        task_id=task_id,
        status="partial",
        artifact_refs=[],
        validation_refs=[],
        failure_evidence_refs=list(next_action.get("evidence_refs") or []),
        cost=WorkerCost(model_calls=0, tool_calls=0),
        summary=(
            "Subagent dispatch recorded; worker execution must produce follow-up "
            "observation, repair, replan, ask, or completion evidence."
        ),
        parent_worker_invocation_id=str(decision.get("parent_worker_invocation_id") or "") or None,
        worker_kind="subagent",
    )
    store.append(workers_path, worker.to_dict(), "worker_invocation")
    store.append(worker_results_path, worker_result.to_dict(), "worker_result")
    return {
        "worker_invocation_id": worker_id,
        "worker_result_id": worker_result_id,
        "runtime_profile_id": runtime_profile_id,
        "worker_status": worker_result.status,
    }


def _validate_subagent_decision(decision: dict[str, Any]) -> None:
    next_action = decision["next_action"]
    capability = next_action.get("capability_ref")
    if not isinstance(capability, dict) or capability.get("type") != "subagent":
        raise ValueError("subagent action requires capability_ref.type == 'subagent'")
    if not str(next_action.get("target_task_id") or "").strip():
        raise ValueError("subagent action requires target_task_id")
    risk = str(next_action.get("risk") or "")
    if risk not in {"low", "medium", "high"}:
        raise ValueError("subagent action requires low, medium, or high risk")
    budget = next_action.get("budget_hint")
    if not isinstance(budget, dict):
        raise ValueError("subagent action requires budget_hint")
    model_calls = budget.get("model_calls", 1)
    tool_budget = budget.get("tool_budget_units", 0)
    if isinstance(model_calls, int | float) and model_calls < 0:
        raise ValueError("subagent action budget_hint.model_calls cannot be negative")
    if isinstance(tool_budget, int | float) and tool_budget < 0:
        raise ValueError("subagent action budget_hint.tool_budget_units cannot be negative")


def _subagent_runtime_profile_id(capability: dict[str, Any], worker_id: str | None = None) -> str:
    if worker_id:
        return f"runtime-profile-{worker_id}"
    name = str(capability.get("name") or "subagent").lower().replace(" ", "-")
    return f"runtime-profile-subagent-{name}"


def _subagent_delegation_brief(decision: dict[str, Any]) -> dict[str, Any]:
    next_action = decision["next_action"]
    expected = next_action.get("expected_observation")
    expected_observation = expected if isinstance(expected, dict) else {}
    return {
        "goal": str(expected_observation.get("summary") or next_action.get("reason") or ""),
        "why": str(next_action.get("reason") or "Model selected subagent delegation."),
        "known_context": {
            "task_id": decision.get("task_id"),
            "target_task_id": next_action.get("target_task_id"),
            "evidence_refs": list(next_action.get("evidence_refs") or []),
        },
        "files_or_commands": {
            "expected_observation": expected_observation,
        },
        "constraints": {
            "risk": next_action.get("risk"),
            "budget_hint": next_action.get("budget_hint") or {},
            "capability_ref": next_action.get("capability_ref") or {},
        },
        "allowed_writes": list(expected_observation.get("allowed_writes") or []),
        "expected_output": [str(expected_observation.get("success_signal") or "subagent observation")],
        "verification_expectation": {
            "success_signal": expected_observation.get("success_signal"),
        },
    }


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def _subagent_worker_id(workers_path: Path, decision: dict[str, Any]) -> str:
    next_index = _jsonl_count(workers_path) + 1
    parent = str(decision.get("parent_worker_invocation_id") or "")
    if parent.startswith("worker-"):
        try:
            parent_index = int(parent.removeprefix("worker-"))
        except ValueError:
            parent_index = 0
        next_index = max(next_index, parent_index + 1)
    return f"worker-{next_index:04d}"


def _subagent_worker_result_id(worker_results_path: Path, decision: dict[str, Any]) -> str:
    next_index = _jsonl_count(worker_results_path) + 1
    parent = str(decision.get("parent_worker_result_id") or "")
    if parent.startswith("worker-result-"):
        try:
            parent_index = int(parent.removeprefix("worker-result-"))
        except ValueError:
            parent_index = 0
        next_index = max(next_index, parent_index + 1)
    return f"worker-result-{next_index:04d}"


def _latest_worker_invocation(
    run_dir: Path,
    validator: SchemaValidator,
    worker_id: str,
) -> dict[str, Any] | None:
    path = run_dir / "workers.jsonl"
    if not path.exists():
        return None
    latest: dict[str, Any] | None = None
    for item in JsonlStore(validator).read_all(path, "worker_invocation"):
        if str(item.get("worker_invocation_id") or "") == worker_id:
            latest = item
    return latest


def _record_subagent_child_plan_ref(
    run_dir: Path,
    validator: SchemaValidator,
    *,
    worker_id: str,
    child_plan_id: str,
) -> None:
    if not worker_id or not child_plan_id:
        return
    worker = _latest_worker_invocation(run_dir, validator, worker_id)
    if not isinstance(worker, dict):
        return
    refs = [str(item) for item in worker.get("child_plan_refs") or []]
    if child_plan_id not in refs:
        refs.append(child_plan_id)
    update = WorkerInvocation(
        worker_invocation_id=worker_id,
        run_id=str(worker.get("run_id") or ""),
        task_id=str(worker.get("task_id") or ""),
        agent_id=str(worker.get("agent_id") or "subagent"),
        runtime_profile_id=str(worker.get("runtime_profile_id") or ""),
        status=str(worker.get("status") or "queued"),
        started_at=str(worker.get("started_at") or now_iso()),
        ended_at=worker.get("ended_at"),
        summary=str(worker.get("summary") or ""),
        delegation_brief=worker.get("delegation_brief"),
        brief_quality=worker.get("brief_quality"),
        parent_worker_invocation_id=worker.get("parent_worker_invocation_id"),
        parent_task_id=worker.get("parent_task_id"),
        worker_kind=worker.get("worker_kind") or "subagent",
        parallel_safety=worker.get("parallel_safety"),
        child_plan_refs=refs,
    )
    JsonlStore(validator).append(run_dir / "workers.jsonl", update.to_dict(), "worker_invocation")


def _decision_point_from_loop_decision(
    decision: dict[str, Any],
    *,
    sequence: int,
) -> dict[str, Any]:
    next_action = decision["next_action"]
    expected = next_action.get("expected_observation")
    expected_observation = expected if isinstance(expected, dict) else {}
    options = _decision_options(expected_observation)
    option_ids = {option["option_id"] for option in options}
    recommended = str(expected_observation.get("recommended_option_id") or options[0]["option_id"])
    default = str(expected_observation.get("default_option_id") or recommended)
    if recommended not in option_ids:
        recommended = options[0]["option_id"]
    if default not in option_ids:
        default = recommended
    return {
        "schema_version": "0.1.0",
        "decision_id": f"decision-{max(1, sequence):04d}",
        "status": "pending",
        "question": str(
            expected_observation.get("question")
            or f"How should Asteria continue after: {next_action['reason']}"
        ),
        "recommended_option_id": recommended,
        "options": options,
        "default_option_id": default,
        "impact": _decision_impact(expected_observation, next_action),
        "selected_option_id": None,
        "created_at": now_iso(),
        "metadata": {
            "kind": "agent_loop_ask",
            "run_id": decision.get("run_id"),
            "task_id": decision.get("task_id"),
            "target_task_id": next_action.get("target_task_id"),
            "agent_loop_decision_id": decision.get("decision_id"),
            "capability_ref": next_action.get("capability_ref") or {},
            "evidence_refs": next_action.get("evidence_refs") or [],
        },
        "resolved_at": None,
    }


def _decision_options(expected_observation: dict[str, Any]) -> list[dict[str, str]]:
    raw_options = expected_observation.get("options")
    if isinstance(raw_options, list):
        options = []
        for index, raw in enumerate(raw_options, start=1):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or raw.get("title") or "").strip()
            if not label:
                continue
            action = str(raw.get("action") or "")
            if action not in {"create_task", "record_constraint", "cancel_scope", "require_replan"}:
                action = "require_replan" if "replan" in label.lower() else "record_constraint"
            options.append(
                {
                    "option_id": str(raw.get("option_id") or f"option-{index}"),
                    "label": label,
                    "tradeoff": str(raw.get("tradeoff") or raw.get("description") or label),
                    "action": action,
                }
            )
        if 2 <= len(options) <= 4:
            return options
    return [
        {
            "option_id": "review_contract",
            "label": "Review contract",
            "tradeoff": "Pause and review scope, budget, route, or recovery direction deliberately.",
            "action": "require_replan",
        },
        {
            "option_id": "stop_and_report",
            "label": "Stop and report",
            "tradeoff": "Stop this loop and preserve the current evidence for manual review.",
            "action": "record_constraint",
        },
    ]


def _decision_impact(
    expected_observation: dict[str, Any],
    next_action: dict[str, Any],
) -> dict[str, str]:
    raw = expected_observation.get("impact")
    impact = raw if isinstance(raw, dict) else {}
    risk = str(impact.get("risk") or next_action.get("risk") or "medium")
    return {
        "scope": _impact_value(impact.get("scope") or "medium"),
        "budget": _impact_value(impact.get("budget") or "medium"),
        "risk": _impact_value(risk),
        "quality": _impact_value(impact.get("quality") or "medium"),
    }


def _impact_value(value: Any) -> str:
    value_str = str(value or "medium").lower()
    return value_str if value_str in {"low", "medium", "high"} else "medium"
