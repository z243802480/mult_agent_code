import pytest

from agent_runtime.core.budget import BudgetController, BudgetExceededError


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
    controller.record_tool_call()
    controller.record_research_call()
    controller.record_context_compaction()

    report = controller.cost_report()
    assert report["run_id"] == "run-1"
    assert report["model_calls"] == 1
    assert report["tool_calls"] == 1
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


def test_budget_controller_reports_pressure_status() -> None:
    report = {
        "model_calls": 8,
        "tool_calls": 1,
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
