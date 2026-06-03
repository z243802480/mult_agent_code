from __future__ import annotations

from asteria_runtime.core.runtime_progress import build_runtime_progress


def test_runtime_progress_exposes_loop_recovery_budget_and_context() -> None:
    progress = build_runtime_progress(
        workflow_state="blocked",
        main_path={
            "path": "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop",
            "active_stage": "repair",
            "next_command": "debug",
            "current_step": "Run `asteria debug`.",
        },
        todo_view={"summary": "1/2 todo item(s) complete."},
        agent_loop_summary={
            "exit_reason": "tool_failed",
            "recommended_command": "debug",
            "rounds_completed": 1,
            "max_rounds": 3,
            "budget": {
                "status": "within_budget",
                "highest_label": "model_calls",
                "highest_ratio": 0.2,
                "model_calls": 2,
                "tool_budget_units": 1,
                "repair_attempts": 0,
            },
            "context_pressure": {
                "status": "near_limit",
                "context_window_ratio": 0.76,
                "latest_context_estimated_tokens": 760000,
                "max_context_estimated_tokens": 760000,
                "context_compactions": 1,
            },
            "recovery_chain": {
                "required": True,
                "satisfied": True,
                "reason": "Loop exit is covered by `repair` recovery semantics.",
                "latest_action": "repair",
                "observation_status": "failed",
                "observation_next_recommended_action": "repair",
            },
        },
    )

    loop = progress["loop"]
    assert loop["exit_reason"] == "tool_failed"
    assert loop["recommended_command"] == "debug"
    assert loop["rounds_completed"] == 1
    assert loop["max_rounds"] == 3
    assert loop["recovery"]["required"] is True
    assert loop["recovery"]["satisfied"] is True
    assert loop["budget"]["status"] == "within_budget"
    assert loop["context_pressure"]["status"] == "near_limit"
