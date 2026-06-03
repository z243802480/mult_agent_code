from __future__ import annotations

from asteria_runtime.core.agent_loop_run_summary import build_agent_loop_run_summary


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
