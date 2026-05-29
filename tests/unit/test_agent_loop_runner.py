from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.agent_loop_runner import AgentLoopRunner
from asteria_runtime.storage.schema_validator import SchemaValidator


def _decision(decision_id: str, action: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "run_id": "run-1",
        "task_id": "task-1",
        "created_at": f"2026-05-29T10:00:0{decision_id[-1]}+08:00",
        "next_action": {
            "action": action,
            "reason": f"{action} is the next step.",
            "target_task_id": "task-1",
            "capability_ref": {
                "type": "subagent" if action == "subagent" else "runtime",
                "name": action,
            },
            "expected_observation": {"summary": f"{action} observation"},
            "risk": "medium",
            "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
            "evidence_refs": [],
        },
    }


def test_agent_loop_runner_persists_two_round_decision_execution_observation(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    runner = AgentLoopRunner(validator)

    rounds = runner.run(
        run_dir=tmp_path,
        initial_decision=_decision("agent-loop-decision-0001", "subagent"),
        decide_next=lambda observation, index: _decision("agent-loop-decision-0002", "stop")
        if index == 1
        else None,
        max_rounds=2,
    )

    assert len(rounds) == 2
    decisions = [
        json.loads(line)
        for line in (tmp_path / "agent_loop_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    executions = [
        json.loads(line)
        for line in (tmp_path / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        json.loads(line)
        for line in (tmp_path / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert [item["decision_id"] for item in decisions] == [
        "agent-loop-decision-0001",
        "agent-loop-decision-0002",
    ]
    assert [item["action"] for item in executions] == ["subagent", "stop"]
    assert [item["observation_type"] for item in observations] == [
        "subagent_result",
        "stop_report",
    ]
    assert observations[0]["next_recommended_action"] == "subagent"
    assert observations[1]["next_recommended_action"] == "stop"


def test_agent_loop_runner_turns_subagent_worker_result_into_parent_observation(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    runner = AgentLoopRunner(validator)

    def execute_subagent(decision: dict, execution: dict) -> dict:
        assert decision["next_action"]["capability_ref"]["type"] == "subagent"
        assert execution["worker_invocation_id"] == "worker-0001"
        return {
            "status": "succeeded",
            "summary": "Subagent worker completed the delegated check.",
            "artifact_refs": ["artifact-subagent-0001"],
            "validation_refs": ["validation-subagent-0001"],
            "failure_evidence_refs": [],
            "cost": {"model_calls": 1, "tool_calls": 2},
        }

    rounds = runner.run(
        run_dir=tmp_path,
        initial_decision=_decision("agent-loop-decision-0001", "subagent"),
        decide_next=lambda observation, index: _decision("agent-loop-decision-0002", "stop")
        if observation["status"] == "succeeded"
        else None,
        max_rounds=2,
        execute_subagent=execute_subagent,
    )

    observations = [
        json.loads(line)
        for line in (tmp_path / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    worker_results = [
        json.loads(line)
        for line in (tmp_path / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    child_plans = [
        json.loads(line)
        for line in (tmp_path / "subagent_child_plans.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    workers = [
        json.loads(line)
        for line in (tmp_path / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert len(rounds) == 2
    assert observations[0]["observation_type"] == "subagent_result"
    assert observations[0]["status"] == "succeeded"
    assert observations[0]["next_recommended_action"] == "stop"
    assert "artifact-subagent-0001" in observations[0]["evidence_refs"]
    assert child_plans[0]["worker_invocation_id"] == "worker-0001"
    assert "subagent-child-plan-0001" in observations[0]["evidence_refs"]
    assert worker_results[-1]["status"] == "succeeded"
    assert worker_results[-1]["child_plan_refs"] == ["subagent-child-plan-0001"]
    assert worker_results[-1]["cost"] == {"model_calls": 1, "tool_calls": 2}
    assert workers[-1]["status"] == "succeeded"
    assert workers[-1]["child_plan_refs"] == ["subagent-child-plan-0001"]
