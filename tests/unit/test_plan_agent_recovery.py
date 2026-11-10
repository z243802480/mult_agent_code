import json
from copy import deepcopy
from pathlib import Path

import pytest

from asteria_runtime.agents.plan_agent import PlanAgent, PlanAgentError
from asteria_runtime.core.budget import BudgetController, BudgetExceededError
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator


def valid_plan() -> dict:
    return {
        "tasks": [
            {
                "task_id": "fix",
                "title": "Repair batch update consistency",
                "description": "Repair document batch updates and verify failure consistency.",
                "task_kind": "implementation",
                "priority": "high",
                "acceptance": ["Batch failures preserve stored documents and original tests pass"],
                "expected_artifacts": ["src/table.py"],
                "expected_changed_files": ["src/table.py"],
                "read_scope": ["tests/test_table.py"],
                "depends_on": [],
                "validation_commands": ["python -m pytest tests/test_table.py -q"],
            }
        ]
    }


class SequenceClient:
    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        content = json.dumps(answer) if isinstance(answer, dict) else str(answer)
        return ChatResponse(content, "stop", TokenUsage(10, 20, 30), "fake", "sequence", {})


def agent(client) -> PlanAgent:
    return PlanAgent(client, SchemaValidator(Path("schemas")))


def test_valid_plan_needs_no_recovery() -> None:
    client = SequenceClient(valid_plan())
    plan = agent(client).generate({"normalized_goal": "Repair document batch updates"})
    assert plan["tasks"][0]["title"] == "Repair batch update consistency"
    assert len(client.requests) == 1


def test_invalid_json_is_returned_to_model_without_mutating_goal_or_first_request() -> None:
    client = SequenceClient('{"tasks": [broken}', valid_plan())
    goal = {"normalized_goal": "Repair document batch updates", "constraints": ["Keep tests"]}
    original = deepcopy(goal)
    errors = []
    plan = agent(client).generate(
        goal,
        run_id="run-recovery",
        model_tier="medium",
        on_invalid_plan=lambda *args: errors.append(args),
    )
    assert goal == original
    assert len(client.requests) == 2
    first, second = client.requests
    assert len(first.messages) == 2
    assert second.messages[:2] == first.messages
    assert second.messages[2].role == "assistant"
    assert second.messages[2].content == '{"tasks": [broken}'
    assert "not valid JSON" in second.messages[3].text()
    assert "complete" in second.messages[3].text().lower()
    assert second.purpose == first.purpose == "task_planning"
    assert second.model_tier == first.model_tier == "medium"
    assert second.metadata["agent_role_contract"] == first.metadata["agent_role_contract"]
    assert second.metadata["run_id"] == first.metadata["run_id"] == "run-recovery"
    assert len(errors) == 1 and errors[0][0] == 1 and errors[0][2] is True
    assert plan["tasks"][0]["verification_policy"]["command_source"] == "planner_task"


@pytest.mark.parametrize(
    "bad",
    [
        {"tasks": []},
        {"tasks": [valid_plan()["tasks"][0], "junk"]},
        {"tasks": [{**valid_plan()["tasks"][0], "verification_policy": {"timeout_seconds": 0}}]},
    ],
)
def test_shape_and_schema_errors_can_be_corrected_by_model(bad: dict) -> None:
    client = SequenceClient(bad, valid_plan())
    plan = agent(client).generate({"normalized_goal": "Repair document batch updates"})
    assert len(client.requests) == 2
    assert plan["tasks"][0]["verification_policy"].get("timeout_seconds") is None


def test_session_profile_is_checked_again_after_recovery() -> None:
    bad = valid_plan()
    bad["tasks"].append({**bad["tasks"][0], "task_id": "second"})
    client = SequenceClient(bad, valid_plan())
    plan = agent(client).generate(
        {"normalized_goal": "Repair document batch updates"},
        execution_profile="session_agent",
    )
    assert len(plan["tasks"]) == 1
    assert "exactly one task" in client.requests[1].messages[-1].text()


def test_repeated_bad_plans_stop_after_one_correction() -> None:
    client = SequenceClient("not JSON", {"tasks": []}, valid_plan())
    errors = []
    with pytest.raises(PlanAgentError, match="no non-empty 'tasks'"):
        agent(client).generate({}, on_invalid_plan=lambda *args: errors.append(args))
    assert len(client.requests) == 2
    assert [(e[0], e[2]) for e in errors] == [(1, True), (2, False)]


@pytest.mark.parametrize(
    "answers,count",
    [([RuntimeError("provider offline")], 1), (["bad JSON", RuntimeError("provider offline")], 2)],
)
def test_transport_failure_is_not_retried_as_bad_format(answers: list, count: int) -> None:
    client = SequenceClient(*answers, valid_plan())
    with pytest.raises(RuntimeError, match="provider offline"):
        agent(client).generate({})
    assert len(client.requests) == count


def test_recovery_feedback_has_a_bounded_previous_response() -> None:
    client = SequenceClient('{"tasks": [oops], "padding": "' + "x" * 30000 + '"}', valid_plan())
    agent(client).generate({"normalized_goal": "Repair document batch updates"})
    second = client.requests[1]
    assert len(second.messages[2].text()) < 13000
    assert "truncat" in second.messages[-1].text().lower()


def test_recovery_uses_the_original_metered_client_and_budget(tmp_path: Path) -> None:
    client = SequenceClient("bad JSON", valid_plan())
    budget = BudgetController({"budgets": {"max_model_calls_per_goal": 1}})
    validator = SchemaValidator(Path("schemas"))
    metered = MeteredModelClient(client, budget, ModelCallLogger(tmp_path, validator))
    with pytest.raises(BudgetExceededError):
        agent(metered).generate({"normalized_goal": "Repair document batch updates"})
    assert len(client.requests) == 1
    calls = [
        json.loads(line)
        for line in (tmp_path / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["status"] for row in calls] == ["success", "failure"]
    assert all(row["purpose"] == "task_planning" for row in calls)
