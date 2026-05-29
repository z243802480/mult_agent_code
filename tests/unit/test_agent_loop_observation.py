from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.agent_loop_observation import (
    build_agent_loop_observation,
    latest_agent_loop_observation,
    persist_agent_loop_observation_for_execution,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def _execution(action: str = "tool") -> dict:
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
        "target": "tool_gateway" if action == "tool" else "subagent_dispatcher",
        "recommended_command": "execute",
        "capability_ref": {"type": "tool", "name": "write_file"},
        "reason": "perform next runtime step",
        "expected_observation": {"summary": "observation recorded"},
        "risk": "medium",
        "budget_hint": {"model_calls": 1},
        "evidence_refs": ["task_execution_evidence.jsonl"],
    }


def test_agent_loop_observation_records_execution_feedback(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    execution = _execution("tool")

    observation = persist_agent_loop_observation_for_execution(
        run_dir=tmp_path,
        validator=validator,
        execution_result=execution,
        status="succeeded",
        summary="Tool action completed.",
        evidence_refs=["validation-0001"],
    )

    assert observation is not None
    assert observation["observation_id"] == "agent-loop-observation-0001"
    assert observation["observation_type"] == "tool_result"
    assert observation["status"] == "succeeded"
    assert observation["next_recommended_action"] is None
    assert "validation-0001" in observation["evidence_refs"]
    assert latest_agent_loop_observation(tmp_path, validator) == observation
    validator.validate("agent_loop_observation", observation)


def test_agent_loop_observation_maps_failed_dispatch_to_repair() -> None:
    observation = build_agent_loop_observation(
        _execution("tool"),
        status="failed",
        summary="Verification failed.",
    )

    assert observation["status"] == "failed"
    assert observation["next_recommended_action"] == "repair"
