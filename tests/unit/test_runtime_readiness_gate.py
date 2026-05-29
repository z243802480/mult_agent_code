from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.runtime_readiness_gate import runtime_readiness_gate
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def _loop_decision(action: str = "replan") -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": "agent-loop-decision-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "created_at": "2026-05-29T10:00:00+08:00",
        "next_action": {
            "action": action,
            "reason": "review timeout exposed a plan gap",
            "target_task_id": "task-1",
            "capability_ref": {
                "type": "subagent" if action == "subagent" else "runtime",
                "name": "subagent" if action == "subagent" else "recovery-review",
            },
            "expected_observation": {"summary": "replan command is available"},
            "risk": "medium",
            "budget_hint": {"model_calls": 1},
            "evidence_refs": ["model_calls.jsonl"],
        },
    }


def _loop_execution(action: str = "replan") -> dict:
    return {
        "schema_version": "0.1.0",
        "execution_id": "agent-loop-execution-0001",
        "decision_id": "agent-loop-decision-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "target_task_id": "task-1",
        "created_at": "2026-05-29T10:00:01+08:00",
        "action": action,
        "status": "dispatched",
        "target": "replan_command",
        "recommended_command": "replan",
        "capability_ref": {
            "type": "subagent" if action == "subagent" else "runtime",
            "name": "subagent" if action == "subagent" else "recovery-review",
        },
        "reason": "review timeout exposed a plan gap",
        "expected_observation": {"summary": "replan command is available"},
        "risk": "medium",
        "budget_hint": {"model_calls": 1},
        "evidence_refs": ["model_calls.jsonl"],
    }


def _loop_observation(
    *,
    action: str = "replan",
    status: str = "pending",
    decision_id: str = "agent-loop-decision-0001",
    execution_id: str = "agent-loop-execution-0001",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "observation_id": "agent-loop-observation-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "target_task_id": "task-1",
        "created_at": "2026-05-29T10:00:02+08:00",
        "observation_type": {
            "tool": "tool_result",
            "subagent": "subagent_result",
            "repair": "repair_result",
            "replan": "replan_result",
            "ask": "decision_pending",
            "stop": "stop_report",
        }[action],
        "source_execution_id": execution_id,
        "source_decision_id": decision_id,
        "status": status,
        "summary": f"{action} observation is {status}.",
        "evidence_refs": ["agent_loop_execution_results.jsonl"],
        "next_recommended_action": "repair" if status == "failed" else None,
    }


def _worker_invocation() -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_invocation_id": "worker-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "agent_id": "subagent",
        "runtime_profile_id": "runtime-profile-subagent-subagent",
        "status": "queued",
        "started_at": "2026-05-29T10:00:01+08:00",
        "ended_at": None,
        "summary": "Dispatch task-1 to subagent.",
    }


def _worker_result(status: str = "partial") -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_result_id": "worker-result-0001",
        "worker_invocation_id": "worker-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "status": status,
        "artifact_refs": [],
        "validation_refs": [],
        "failure_evidence_refs": [],
        "cost": {"model_calls": 0, "tool_calls": 0},
        "summary": "Subagent dispatch recorded.",
    }


def test_runtime_readiness_gate_blocks_missing_loop_decision_for_failed_observation(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    (tmp_path / ".asteria" / "runs" / "run-1").mkdir(parents=True)

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={
            "failed_observation_count": 1,
            "recommended_route": "repair",
            "evidence_refs": ["tool_observations.jsonl"],
        },
    )

    assert gate["status"] == "blocked"
    observation = next(check for check in gate["checks"] if check["name"] == "observation_next_action")
    assert "AgentLoopDecision" in observation["summary"]


def test_runtime_readiness_gate_surfaces_recovery_loop_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("replan"),
        "agent_loop_decision",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        _loop_execution("replan"),
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="replan"),
        "agent_loop_observation",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={
            "run_id": "run-1",
            "task_id": "task-1",
            "failed_observation_count": 1,
            "recommended_route": "repair",
            "evidence_refs": ["tool_observations.jsonl"],
        },
    )

    observation = next(check for check in gate["checks"] if check["name"] == "observation_next_action")
    assert observation["status"] == "review"
    assert "explicit `replan` AgentLoopDecision" in observation["summary"]
    assert observation["recommended_action"] == (
        "Run `asteria replan` to continue the recorded recovery decision."
    )
    execution = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution["status"] == "ready"
    assert "replan_command" in execution["summary"]


def test_runtime_readiness_gate_blocks_loop_decision_without_runtime_execution(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("repair"),
        "agent_loop_decision",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution["status"] == "blocked"
    assert "no matching Runtime execution result" in execution["summary"]


def test_runtime_readiness_gate_requires_subagent_worker_evidence(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("subagent"),
        "agent_loop_decision",
    )
    execution = _loop_execution("subagent")
    execution.update(
        {
            "target": "subagent_dispatcher",
            "recommended_command": "execute",
            "runtime_profile_id": "runtime-profile-subagent-subagent",
        }
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert "missing worker dispatch evidence" in execution_check["summary"]


def test_runtime_readiness_gate_accepts_subagent_worker_dispatch(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("subagent"),
        "agent_loop_decision",
    )
    execution = _loop_execution("subagent")
    execution.update(
        {
            "target": "subagent_dispatcher",
            "recommended_command": "execute",
            "worker_invocation_id": "worker-0001",
            "worker_result_id": "worker-result-0001",
            "runtime_profile_id": "runtime-profile-subagent-subagent",
            "worker_status": "partial",
        }
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(run_dir / "workers.jsonl", _worker_invocation(), "worker_invocation")
    JsonlStore(validator).append(
        run_dir / "worker_results.jsonl",
        _worker_result("partial"),
        "worker_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="subagent"),
        "agent_loop_observation",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "ready"


def test_runtime_readiness_gate_blocks_execution_without_observation(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("replan"),
        "agent_loop_decision",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        _loop_execution("replan"),
        "agent_loop_execution_result",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert "no matching AgentLoopObservation" in execution_check["summary"]


def test_runtime_readiness_gate_blocks_failed_observation_without_recovery_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("tool"),
        "agent_loop_decision",
    )
    execution = _loop_execution("tool")
    execution["target"] = "tool_gateway"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="tool", status="failed"),
        "agent_loop_observation",
    )
    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "blocked"
    assert "no follow-up AgentLoopDecision" in execution_check["summary"]


def test_runtime_readiness_gate_accepts_failed_observation_with_recovery_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    tool_decision = _loop_decision("tool")
    tool_decision["decision_id"] = "agent-loop-decision-0001"
    repair_decision = _loop_decision("repair")
    repair_decision["decision_id"] = "agent-loop-decision-0002"
    repair_decision["created_at"] = "2026-05-29T10:00:03+08:00"
    JsonlStore(validator).append(run_dir / "agent_loop_decisions.jsonl", tool_decision, "agent_loop_decision")
    JsonlStore(validator).append(run_dir / "agent_loop_decisions.jsonl", repair_decision, "agent_loop_decision")
    tool_execution = _loop_execution("tool")
    tool_execution["target"] = "tool_gateway"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        tool_execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="tool", status="failed"),
        "agent_loop_observation",
    )
    repair_execution = _loop_execution("repair")
    repair_execution["execution_id"] = "agent-loop-execution-0002"
    repair_execution["decision_id"] = "agent-loop-decision-0002"
    repair_execution["target"] = "debug_agent"
    repair_execution["recommended_command"] = "debug"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        repair_execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(
            action="repair",
            decision_id="agent-loop-decision-0002",
            execution_id="agent-loop-execution-0002",
        ),
        "agent_loop_observation",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "ready"
    assert "debug_agent" in execution_check["summary"]


def test_runtime_readiness_gate_reviews_capability_mismatch(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "tool",
                                    "name": "read_file",
                                    "selection_state": "selected",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        run_dir / "capability_decisions.jsonl",
        {
            "capability_type": "tool",
            "capability": "run_command",
            "decision": {"decision": "allow"},
        },
        None,
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "review"
    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "review"
    assert "not fully aligned" in capability["summary"]
