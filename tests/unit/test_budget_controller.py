import pytest

from asteria_runtime.core.budget import (
    BudgetController,
    BudgetExceededError,
    resolve_budget_limits,
)
from asteria_runtime.core.context_budget import estimate_text_tokens


def policy(max_model_calls: int = 3, max_tool_calls: int = 3) -> dict:
    return {
        "budgets": {
            "max_model_calls_per_goal": max_model_calls,
            "max_tool_calls_per_goal": max_tool_calls,
            "max_total_minutes_per_goal": 30,
            "max_iterations_per_goal": 8,
            "max_repair_attempts_total": 2,
            "max_repair_attempts_per_task": 1,
            "max_replans_per_task": 1,
            "max_research_calls": 1,
            "max_user_decisions": 1,
        }
    }


def test_budget_controller_records_usage_and_report() -> None:
    controller = BudgetController(policy(), run_id="run-1")

    controller.record_model_call("strong", input_tokens=10, output_tokens=5)
    controller.record_tool_call("read_file")
    controller.record_tool_call("write_file")
    controller.record_research_call()
    controller.record_context_compaction()

    report = controller.cost_report()
    assert report["run_id"] == "run-1"
    assert report["model_calls"] == 1
    assert report["tool_calls"] == 2
    assert report["tool_budget_units"] == 2
    assert report["tool_call_breakdown"] == {"read_only": 1, "write": 1}
    assert report["research_calls"] == 1
    assert report["strong_model_calls"] == 1
    assert report["estimated_input_tokens"] == 10
    assert report["estimated_output_tokens"] == 5
    assert report["context_compactions"] == 1


def test_budget_controller_can_reserve_call_then_add_tokens() -> None:
    controller = BudgetController(policy(), run_id="run-1")

    controller.record_model_call("strong")
    controller.record_model_tokens(input_tokens=12, output_tokens=5)

    report = controller.cost_report()
    assert report["model_calls"] == 1
    assert report["strong_model_calls"] == 1
    assert report["estimated_input_tokens"] == 12
    assert report["estimated_output_tokens"] == 5


def test_budget_controller_blocks_after_limit() -> None:
    controller = BudgetController(policy(max_model_calls=1))
    controller.record_model_call()

    with pytest.raises(BudgetExceededError):
        controller.record_model_call()


def test_budget_controller_weights_tool_budget_by_risk() -> None:
    controller = BudgetController(policy(max_tool_calls=3))

    for _ in range(20):
        controller.record_tool_call("read_file")
    controller.record_tool_call("run_tests")
    controller.record_tool_call("write_file")

    report = controller.cost_report()
    assert report["tool_calls"] == 22
    assert report["tool_budget_units"] == 3
    assert report["status"] == "near_limit"

    with pytest.raises(BudgetExceededError):
        controller.record_tool_call("run_command")


def test_budget_controller_uses_active_budget_profile() -> None:
    config = policy(max_model_calls=1, max_tool_calls=1)
    config["active_budget_profile"] = "autonomous_long_task"
    config["budget_profiles"] = {
        "autonomous_long_task": {
            "max_model_calls_per_goal": 4,
            "max_tool_calls_per_goal": 6,
        }
    }
    controller = BudgetController(config, run_id="run-1")

    for _ in range(4):
        controller.record_model_call()
    controller.record_tool_call("write_file")
    controller.record_tool_call("run_command")
    controller.record_tool_call("run_tests")

    report = controller.cost_report()
    assert report["model_calls"] == 4
    assert report["tool_budget_units"] == 5
    assert resolve_budget_limits(config)["max_tool_calls_per_goal"] == 6

    with pytest.raises(BudgetExceededError):
        controller.record_tool_call("write_file")


def test_budget_controller_reports_pressure_status() -> None:
    report = {
        "model_calls": 8,
        "tool_calls": 80,
        "tool_budget_units": 1,
        "repair_attempts": 0,
        "research_calls": 0,
        "user_decisions": 0,
    }
    config = policy(max_model_calls=10)
    config["context"] = {"compaction_threshold": 0.75, "hard_stop_threshold": 0.9}

    pressure = BudgetController.pressure(config, report)

    assert pressure["status"] == "near_limit"
    assert pressure["highest_label"] == "model_calls"
    assert pressure["highest_ratio"] == 0.8


def test_budget_controller_tracks_context_window_pressure() -> None:
    config = policy(max_model_calls=10, max_tool_calls=10)
    config["context"] = {
        "model_context_window_tokens": 100,
        "compaction_threshold": 0.75,
        "hard_stop_threshold": 0.9,
    }
    controller = BudgetController(config, run_id="run-1")

    controller.record_context_estimate(80)

    report = controller.cost_report()
    assert report["latest_context_estimated_tokens"] == 80
    assert report["max_context_estimated_tokens"] == 80
    assert report["context_window_tokens"] == 100
    assert report["context_window_ratio"] == 0.8
    assert report["context_pressure_status"] == "near_limit"

    pressure = BudgetController.pressure(config, report)
    assert pressure["status"] == "near_limit"
    assert pressure["highest_label"] == "context_window"


def test_budget_controller_tracks_context_sections_and_duplicates() -> None:
    controller = BudgetController(policy(), run_id="run-1")

    controller.record_context_estimate(
        42,
        sections={"prompt_envelope": 12, "tool_output": 30},
        duplicate_content_hashes=["abc123"],
    )
    controller.record_context_estimate(
        30,
        sections={"prompt_envelope": 20, "memory": 10},
        duplicate_content_hashes=["abc123", "def456"],
    )

    report = controller.cost_report()
    assert report["latest_context_sections"] == {"memory": 10, "prompt_envelope": 20}
    assert report["max_context_sections"] == {
        "memory": 10,
        "prompt_envelope": 20,
        "tool_output": 30,
    }
    assert report["context_duplicate_content_hashes"] == ["abc123", "def456"]


def test_context_token_estimator_counts_cjk_more_tightly() -> None:
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("中文") == 2


def test_budget_pressure_uses_active_budget_profile() -> None:
    config = policy(max_model_calls=1, max_tool_calls=1)
    config["active_budget_profile"] = "autonomous_long_task"
    config["budget_profiles"] = {
        "autonomous_long_task": {
            "max_model_calls_per_goal": 10,
            "max_tool_calls_per_goal": 10,
            "max_repair_attempts_total": 10,
            "max_research_calls": 10,
            "max_user_decisions": 10,
        }
    }
    config["context"] = {"compaction_threshold": 0.75, "hard_stop_threshold": 0.9}

    pressure = BudgetController.pressure(config, {"model_calls": 8, "tool_budget_units": 0})

    assert pressure["status"] == "near_limit"
    assert pressure["highest_label"] == "model_calls"
    assert pressure["highest_ratio"] == 0.8
