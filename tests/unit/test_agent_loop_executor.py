from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.agent_loop_executor import (
    build_agent_loop_execution_result,
    latest_agent_loop_execution_result,
    persist_agent_loop_execution_result,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def _decision(action: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": f"decision-{action}",
        "run_id": "run-1",
        "task_id": "task-1",
        "created_at": "2026-05-29T00:00:00Z",
        "next_action": {
            "action": action,
            "reason": f"{action} is the safest next step.",
            "target_task_id": "task-1",
            "capability_ref": {
                "type": "subagent" if action == "subagent" else "runtime",
                "name": action,
            },
            "expected_observation": {"summary": "observation recorded"},
            "risk": "medium",
            "budget_hint": {"model_calls": 1},
            "evidence_refs": ["evidence.jsonl"],
        },
    }


def test_agent_loop_executor_maps_all_next_actions_to_runtime_targets() -> None:
    expected = {
        "tool": ("tool_gateway", "dispatched", "execute"),
        "subagent": ("subagent_dispatcher", "dispatched", "execute"),
        "repair": ("debug_agent", "dispatched", "debug"),
        "replan": ("replan_command", "dispatched", "replan"),
        "ask": ("decision_point", "waiting_user", "decide --list"),
        "stop": ("stop_report", "stopped", "status --debug"),
    }

    for action, (target, status, command) in expected.items():
        result = build_agent_loop_execution_result(_decision(action))

        assert result["action"] == action
        assert result["target"] == target
        assert result["status"] == status
        assert result["recommended_command"] == command
        SchemaValidator(Path("schemas")).validate("agent_loop_execution_result", result)


def test_agent_loop_executor_persists_latest_execution_result(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    decision = _decision("replan")

    result = persist_agent_loop_execution_result(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
    )

    assert result is not None
    assert result["execution_id"] == "agent-loop-execution-0001"
    assert result["target"] == "replan_command"
    assert latest_agent_loop_execution_result(tmp_path, validator) == result


def test_agent_loop_executor_records_worker_evidence_for_subagent_dispatch(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    decision = _decision("subagent")

    result = persist_agent_loop_execution_result(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
    )

    assert result is not None
    assert result["worker_invocation_id"] == "worker-0001"
    assert result["worker_result_id"] == "worker-result-0001"
    assert result["runtime_profile_id"] == "runtime-profile-subagent-subagent"
    workers = (tmp_path / "workers.jsonl").read_text(encoding="utf-8")
    worker_results = (tmp_path / "worker_results.jsonl").read_text(encoding="utf-8")
    assert "worker-0001" in workers
    assert "worker-result-0001" in worker_results


def test_agent_loop_executor_can_create_decision_point_for_runtime_owned_ask(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    decision = _decision("ask")
    decision["next_action"]["expected_observation"] = {
        "question": "Provider recovery needs user direction. Continue?",
        "options": [
            {
                "option_id": "retry",
                "label": "Retry",
                "tradeoff": "Spend one more model call on recovery.",
                "action": "require_replan",
            },
            {
                "option_id": "stop",
                "label": "Stop",
                "tradeoff": "Preserve evidence and stop the loop.",
                "action": "record_constraint",
            },
        ],
        "recommended_option_id": "retry",
    }

    result = persist_agent_loop_execution_result(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
        create_decision_point=True,
    )

    assert result is not None
    assert result["decision_point_id"] == "decision-0001"
    decisions = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8")
    assert "Provider recovery needs user direction" in decisions
    assert latest_agent_loop_execution_result(tmp_path, validator) == result
