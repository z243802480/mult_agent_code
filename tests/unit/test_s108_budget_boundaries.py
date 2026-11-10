"""Long turns check existing cost boundaries before model and tool batches."""
from types import SimpleNamespace

from tests.unit.test_model_driven_turn import (
    FakeModelClient, FakeToolResult, FakeToolRunner, _json_resp, _run,
)


def test_already_exhausted_budget_makes_no_model_or_tool_call():
    model = FakeModelClient([])
    tools = FakeToolRunner([])
    result = _run(model, tools, transport="json", budget_exhausted=lambda: True)
    assert result.stop_reason == "budget_hard_stop"
    assert result.iterations == 0 and model.requests == [] and tools.calls_seen == []


def test_budget_reached_by_response_does_not_execute_its_proposed_batch():
    model = FakeModelClient([_json_resp("write", [{"tool_name": "write_file", "args": {"path": "late.py"}}])])
    tools = FakeToolRunner([])
    result = _run(model, tools, transport="json", budget_exhausted=lambda: len(model.requests) >= 1)
    assert result.stop_reason == "budget_hard_stop"
    assert len(model.requests) == 1 and tools.calls_seen == []


def test_tool_budget_stops_next_model_call_and_preserves_completed_observations():
    model = FakeModelClient([_json_resp("read", [{"tool_name": "read_file", "args": {"path": "a.py"}}])])
    tools = FakeToolRunner([[FakeToolResult(summary="actual completed prefix")]])
    result = _run(model, tools, transport="json", budget_exhausted=lambda: bool(tools.calls_seen))
    assert result.stop_reason == "budget_hard_stop"
    assert len(model.requests) == 1 and len(result.observations) == 1
    assert result.observations[0].ok
    assert result.observations[0].summary == "actual completed prefix"


def test_user_pause_still_takes_priority_over_budget_boundary():
    result = _run(FakeModelClient([]), FakeToolRunner([]), transport="json",
                  pause_requested=lambda: True, budget_exhausted=lambda: True)
    assert result.status == "paused" and result.stop_reason == ""


def test_cost_boundary_is_not_hidden_by_higher_context_pressure():
    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.core.budget import BudgetController
    policy = {"budgets": {"max_model_calls_per_goal": 20, "max_tool_calls_per_goal": 100,
                          "max_repair_attempts_total": 4, "max_research_calls": 10,
                          "max_user_decisions": 10},
              "context": {"hard_stop_threshold": 0.9}}
    budget = BudgetController(policy)
    budget.usage.model_calls = 18
    budget.usage.context_window_ratio = 1.2
    context = SimpleNamespace(policy=policy, budget=budget)
    assert ExecuteCommand._task_budget_hard_stop(context)
    budget.usage.model_calls = 17
    assert not ExecuteCommand._task_budget_hard_stop(context)
    budget.usage.tool_budget_units = 90
    assert ExecuteCommand._task_budget_hard_stop(context)


def test_local_expert_checks_shared_budget_before_starting_its_model():
    from asteria_runtime.core.budget import BudgetController
    from asteria_runtime.core.worker_executor import LocalExecutor, SubagentRequest
    policy = {"budgets": {"max_model_calls_per_goal": 20, "max_tool_calls_per_goal": 100,
                          "max_repair_attempts_total": 4, "max_research_calls": 10,
                          "max_user_decisions": 10}}
    budget = BudgetController(policy)
    budget.usage.model_calls = 18
    model = FakeModelClient([])
    request = SubagentRequest(role="Reviewer", task={"task_id": "child", "allowed_tools": []},
                              system_prompt="system", user_prompt="review", available_tools=[],
                              model_tier="medium", max_iterations=200)
    result = LocalExecutor().run_subagent(request, model_client=model, tool_runner=FakeToolRunner([]),
                                         context=SimpleNamespace(budget=budget))
    assert not result.ok and result.status == "budget_exhausted"
    assert result.iterations == 0 and model.requests == []
    assert result.data["stop_reason"] == "budget_hard_stop"
