import json
from pathlib import Path

import pytest

from asteria_runtime.agents.plan_agent import PlanAgent, PlanAgentError
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator

pytestmark = pytest.mark.workflow


def _plan_payload() -> dict:
    return {
        "tasks": [
            {
                "task_id": "t1",
                "title": "实现密码评分模块",
                "description": "实现本地密码强度评分函数，返回 0-4 分与一句中文评语。",
                "task_kind": "implementation",
                "priority": "must",
                "acceptance": [
                    "password.py 存在且 score() 返回整数评分",
                    "python -m pytest tests/ 通过",
                ],
                "expected_artifacts": ["password.py"],
                "expected_changed_files": ["password.py"],
                "depends_on": [],
            },
            {
                "task_id": "t2",
                "title": "补测试并跑通",
                "description": "为评分函数补单元测试并确认全部通过。",
                "task_kind": "verification",
                "priority": "should",
                "acceptance": ["tests/test_password.py 覆盖弱中强三档评分"],
                "expected_artifacts": ["tests/test_password.py"],
                "expected_changed_files": ["tests/test_password.py"],
                "depends_on": ["t1", "ghost"],
            },
        ]
    }


class FakeTaskPlanClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        content = (
            json.dumps(self.payload, ensure_ascii=False)
            if isinstance(self.payload, (dict, list))
            else str(self.payload)
        )
        return ChatResponse(
            content=content,
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


class _RejectingValidator:
    def validate(self, name: str, data: object) -> None:
        raise SchemaValidationError("schema rejected")


def _agent(payload: object, validator: SchemaValidator | None = None) -> PlanAgent:
    return PlanAgent(FakeTaskPlanClient(payload), validator or SchemaValidator(Path.cwd() / "schemas"))


def test_plan_agent_normalizes_model_tasks_and_hardens_contracts() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "构建本地优先密码测试工具",
        "expanded_requirements": [],
    }

    plan = _agent(_plan_payload()).generate(goal_spec, run_id="run-1")

    assert plan["schema_version"] == "0.1.0"
    assert [task["task_id"] for task in plan["tasks"]] == ["task-0001", "task-0002"]
    first, second = plan["tasks"]
    # canonical dep rewriting: alias t1 -> task-0001; unknown "ghost" dropped and disclosed
    assert second["depends_on"] == ["task-0001"]
    assert "ghost" in second["notes"]
    assert first["status"] == "ready" and second["status"] == "backlog"
    # enum-safe normalization: model priority vocabulary maps onto the task schema
    assert first["priority"] == "high" and second["priority"] == "medium"
    # same hardening chain as the template branch
    for task in plan["tasks"]:
        assert task["completion_contract"]
        assert "commands" in task["verification_policy"]
        assert task["multi_agent_strategy"]["mode"]
        assert "PlannerAgent (model)" in task["notes"]
    # the model call rides the task_planning purpose / PlannerAgent role contract
    assert plan["tasks"][0]["allowed_tools"]
    assert "write_file" in first["allowed_tools"]
    # verification-kind task keeps read-only tools (its own contract, no write tool needed)
    assert "write_file" not in second["allowed_tools"]


def test_plan_agent_sends_task_planning_request_with_role_contract() -> None:
    client = FakeTaskPlanClient(_plan_payload())
    PlanAgent(client, SchemaValidator(Path.cwd() / "schemas")).generate(
        {"normalized_goal": "x" * 10, "expanded_requirements": []},
        run_id="run-9",
        model_tier="strong",
    )
    request = client.requests[0]
    assert request.purpose == "task_planning"
    assert request.metadata["agent_id"] == "PlannerAgent"
    assert request.metadata["agent_role_contract"]["purpose"] == "task_planning"
    assert request.metadata["run_id"] == "run-9"
    assert "GoalSpec" in request.messages[1].content


def test_plan_agent_session_agent_single_task_gets_widened_write_surface() -> None:
    payload = {"tasks": [_plan_payload()["tasks"][0]]}
    goal_spec = {"normalized_goal": "构建本地优先密码测试工具", "expanded_requirements": []}

    plan = _agent(payload).generate(goal_spec, execution_profile="session_agent")

    task = plan["tasks"][0]
    assert task["execution_profile"] == "session_agent"
    assert task["read_scope"] == []
    assert "implementation artifact" in task["write_scope"]


def test_plan_agent_rejects_multi_task_plan_under_session_agent() -> None:
    goal_spec = {"normalized_goal": "构建本地优先密码测试工具", "expanded_requirements": []}
    with pytest.raises(PlanAgentError, match="exactly one task"):
        _agent(_plan_payload()).generate(goal_spec, execution_profile="session_agent")


def test_plan_agent_rejects_non_json_and_taskless_responses() -> None:
    goal_spec = {"normalized_goal": "构建本地优先密码测试工具", "expanded_requirements": []}
    with pytest.raises(PlanAgentError, match="not valid JSON"):
        _agent("sorry, I cannot help with that").generate(goal_spec)
    with pytest.raises(PlanAgentError, match="no non-empty 'tasks'"):
        _agent({"goal_id": "goal-0001", "normalized_goal": "a goal spec, not a plan"}).generate(
            goal_spec
        )
    with pytest.raises(PlanAgentError, match="cap is"):
        _agent({"tasks": [{"title": f"task {i} description here"} for i in range(20)]}).generate(
            goal_spec
        )


def test_plan_agent_surfaces_schema_failures_as_plan_agent_error() -> None:
    goal_spec = {"normalized_goal": "构建本地优先密码测试工具", "expanded_requirements": []}
    agent = PlanAgent(FakeTaskPlanClient(_plan_payload()), _RejectingValidator())  # type: ignore[arg-type]
    with pytest.raises(PlanAgentError, match="schema validation"):
        agent.generate(goal_spec)
