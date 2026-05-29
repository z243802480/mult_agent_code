from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.core.agent_loop_decision import (
    AgentLoopDecisionError,
    latest_agent_loop_decision,
    normalize_agent_loop_decision,
    persist_agent_loop_decision,
    persist_runtime_agent_loop_decision,
    recommended_command_for_next_action,
    validate_decision_matches_execution_action,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_agent_loop_decision_normalizes_tool_action_from_execution_action(tmp_path: Path) -> None:
    task = {"task_id": "task-1", "risk": "medium"}
    action = {
        "task_id": "task-1",
        "summary": "write artifact",
        "tool_calls": [{"tool_name": "write_file", "args": {"path": "a.txt"}}],
        "verification": [],
        "runtime_requests": [],
    }

    decision = normalize_agent_loop_decision(action, task=task, run_id="run-1")

    next_action = decision["next_action"]
    assert next_action["action"] == "tool"
    assert next_action["target_task_id"] == "task-1"
    assert next_action["capability_ref"] == {"type": "tool", "name": "write_file"}
    SchemaValidator(Path("schemas")).validate("agent_loop_decision", decision)
    persist_agent_loop_decision(
        run_dir=tmp_path,
        validator=SchemaValidator(Path("schemas")),
        decision=decision,
    )
    assert latest_agent_loop_decision(tmp_path, SchemaValidator(Path("schemas"))) == decision


def test_agent_loop_decision_requires_action_to_match_execution_shape() -> None:
    task = {"task_id": "task-1"}
    action = {
        "task_id": "task-1",
        "summary": "ask for scope",
        "tool_calls": [],
        "verification": [],
        "runtime_requests": [],
        "agent_loop_decision": {
            "next_action": {
                "action": "ask",
                "reason": "need approval",
                "target_task_id": "task-1",
                "capability_ref": {"type": "runtime", "name": "decision_point"},
                "expected_observation": {"summary": "decision recorded"},
                "risk": "medium",
                "budget_hint": {},
                "evidence_refs": [],
            }
        },
    }

    decision = normalize_agent_loop_decision(action, task=task, run_id="run-1")

    with pytest.raises(AgentLoopDecisionError):
        validate_decision_matches_execution_action(decision, action)


def test_agent_next_action_maps_to_user_command() -> None:
    assert recommended_command_for_next_action({"action": "repair"}) == "debug"
    assert recommended_command_for_next_action({"action": "replan"}) == "replan"
    assert recommended_command_for_next_action({"action": "ask"}) == "decide --list"


def test_runtime_can_record_recovery_failure_decision(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))

    decision = persist_runtime_agent_loop_decision(
        run_dir=tmp_path,
        validator=validator,
        run_id="run-1",
        task_id="task-1",
        action="repair",
        reason="Review timed out before next action.",
        capability_name="recovery-review",
        expected_observation={"summary": "debug route recorded"},
        evidence_refs=["user_progress.jsonl"],
    )

    assert decision is not None
    assert decision["next_action"]["action"] == "repair"
    assert decision["next_action"]["capability_ref"] == {
        "type": "runtime",
        "name": "recovery-review",
    }
    assert latest_agent_loop_decision(tmp_path, validator) == decision
