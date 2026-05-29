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
