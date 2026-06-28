from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.agent_loop_observation import (
    persist_agent_loop_observation_for_execution,
)
from asteria_runtime.core.agent_loop_run_summary import (
    build_agent_loop_run_summary,
    persist_agent_loop_run_summary,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_agent_loop_run_summary_records_budget_context_and_recovery_chain() -> None:
    summary = build_agent_loop_run_summary(
        run_id="run-1",
        task_id="task-1",
        status="blocked",
        exit_reason="tool_failed",
        rounds_completed=1,
        max_rounds=3,
        summary="Tool failed and needs repair.",
        recommended_command="debug",
        latest_decision={
            "decision_id": "agent-loop-decision-0001",
            "next_action": {"action": "tool"},
        },
        latest_execution={
            "execution_id": "agent-loop-execution-0001",
            "action": "tool",
        },
        latest_observation={
            "observation_id": "agent-loop-observation-0001",
            "status": "failed",
            "next_recommended_action": "repair",
        },
        budget={
            "status": "within_budget",
            "highest_label": "model_calls",
            "highest_ratio": 0.2,
            "model_calls": 2,
            "tool_calls": 1,
            "tool_budget_units": 1,
            "repair_attempts": 0,
            "warnings": [],
        },
        context_pressure={
            "status": "within_budget",
            "context_window_ratio": 0.1,
            "context_window_tokens": 100000,
            "latest_context_estimated_tokens": 1000,
            "max_context_estimated_tokens": 1000,
            "context_compactions": 0,
            "duplicate_content_hash_count": 0,
        },
    )

    assert summary["budget"]["model_calls"] == 2
    assert summary["context_pressure"]["context_window_ratio"] == 0.1
    assert summary["recovery_chain"]["required"] is True
    assert summary["recovery_chain"]["satisfied"] is True
    assert summary["recovery_chain"]["observation_next_recommended_action"] == "repair"


def test_agent_loop_run_summary_marks_failed_observation_without_recovery_unsatisfied() -> None:
    summary = build_agent_loop_run_summary(
        run_id="run-1",
        task_id="task-1",
        status="blocked",
        exit_reason="tool_failed",
        rounds_completed=1,
        max_rounds=3,
        summary="Tool failed without a recovery decision.",
        recommended_command="debug",
        latest_decision={
            "decision_id": "agent-loop-decision-0001",
            "next_action": {"action": "tool"},
        },
        latest_execution={
            "execution_id": "agent-loop-execution-0001",
            "action": "tool",
        },
        latest_observation={
            "observation_id": "agent-loop-observation-0001",
            "status": "failed",
        },
    )

    assert summary["recovery_chain"]["required"] is True
    assert summary["recovery_chain"]["satisfied"] is False


def test_persist_run_summary_attaches_loop_quality_warning(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    for index in range(1, 4):
        persist_agent_loop_observation_for_execution(
            run_dir=tmp_path,
            validator=validator,
            execution_result={
                "action": "tool",
                "run_id": "run-1",
                "task_id": "task-1",
                "target_task_id": "task-1",
                "execution_id": f"agent-loop-execution-000{index}",
                "decision_id": f"agent-loop-decision-000{index}",
            },
            status="failed",
            summary="verification failed: greet.py missing",
            next_recommended_action="repair",
        )

    record = build_agent_loop_run_summary(
        run_id="run-1",
        task_id="task-1",
        status="blocked",
        exit_reason="max_rounds",
        rounds_completed=3,
        max_rounds=5,
        summary="Task stalled across rounds.",
        recommended_command="status --debug",
    )
    persisted = persist_agent_loop_run_summary(
        run_dir=tmp_path, validator=validator, summary=record
    )

    assert persisted is not None
    loop_quality = persisted["loop_quality"]
    assert loop_quality["warn"] is True
    assert loop_quality["repeated_failed_verifications"] >= 3
    assert loop_quality["hard_block"] is False
    assert loop_quality["mode"] == "observe_then_warn"


def test_persist_run_summary_loop_quality_clean_when_no_spin(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    persist_agent_loop_observation_for_execution(
        run_dir=tmp_path,
        validator=validator,
        execution_result={
            "action": "tool",
            "run_id": "run-1",
            "task_id": "task-1",
            "target_task_id": "task-1",
            "execution_id": "agent-loop-execution-0001",
            "decision_id": "agent-loop-decision-0001",
        },
        status="succeeded",
        summary="wrote greet.py",
        next_recommended_action="stop",
    )

    record = build_agent_loop_run_summary(
        run_id="run-1",
        task_id="task-1",
        status="completed",
        exit_reason="completed",
        rounds_completed=1,
        max_rounds=5,
        summary="Task completed.",
        recommended_command="review",
    )
    persisted = persist_agent_loop_run_summary(
        run_dir=tmp_path, validator=validator, summary=record
    )

    assert persisted["loop_quality"]["warn"] is False
    assert persisted["loop_quality"]["severity"] == "ok"
