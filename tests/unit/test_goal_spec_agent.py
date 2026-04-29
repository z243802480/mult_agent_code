from pathlib import Path

import pytest

from agent_runtime.agents.goal_spec_agent import GoalSpecAgent, GoalSpecError
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.storage.schema_validator import SchemaValidator


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


def valid_goal_spec_json() -> str:
    return """{
      "schema_version": "0.1.0",
      "goal_id": "goal-0001",
      "original_goal": "做一个密码测试工具",
      "normalized_goal": "构建本地优先密码测试工具",
      "goal_type": "software_tool",
      "assumptions": ["本地运行"],
      "constraints": ["privacy_safe"],
      "non_goals": ["不证明绝对安全"],
      "expanded_requirements": [
        {
          "id": "req-0001",
          "priority": "must",
          "description": "提供密码强度评分",
          "source": "inferred",
          "acceptance": ["输入密码后显示评分"]
        }
      ],
      "target_outputs": ["local_cli"],
      "definition_of_done": ["可以运行"],
      "verification_strategy": ["unit_tests"],
      "budget": {"max_iterations": 8, "max_model_calls": 60}
    }"""


def test_goal_spec_agent_generates_valid_goal_spec() -> None:
    agent = GoalSpecAgent(FakeClient(valid_goal_spec_json()), SchemaValidator(Path("schemas")))

    result = agent.generate("做一个密码测试工具", {"project": {}}, "run-1")

    assert result["goal_id"] == "goal-0001"
    assert result["expanded_requirements"][0]["priority"] == "must"


def test_goal_spec_agent_rejects_invalid_json() -> None:
    agent = GoalSpecAgent(FakeClient("not json"), SchemaValidator(Path("schemas")))

    with pytest.raises(GoalSpecError):
        agent.generate("goal", {}, "run-1")


def test_goal_spec_agent_normalizes_common_model_shape_drift() -> None:
    content = """{
      "goal_id": "goal-0001",
      "original_goal": "create a file",
      "normalized_goal": "Create a simple local file",
      "goal_type": "tool",
      "assumptions": [{"description": "local only"}],
      "constraints": [],
      "non_goals": null,
      "expanded_requirements": [
        {
          "description": "Create hello_runtime.txt",
          "acceptance": [{"description": "file exists"}]
        }
      ],
      "target_outputs": [{"path": "hello_runtime.txt"}],
      "definition_of_done": [{"description": "file exists"}],
      "verification_strategy": "filesystem check",
      "budget": {"max_iterations": 1}
    }"""
    agent = GoalSpecAgent(FakeClient(content), SchemaValidator(Path("schemas")))

    result = agent.generate("create a file", {}, "run-1")

    assert result["schema_version"] == "0.1.0"
    assert result["goal_type"] == "unknown"
    assert result["assumptions"] == ["local only"]
    assert result["non_goals"] == []
    assert result["target_outputs"] == ["hello_runtime.txt"]
    assert result["expanded_requirements"][0]["priority"] == "must"
    assert result["expanded_requirements"][0]["source"] == "inferred"
    assert result["expanded_requirements"][0]["acceptance"] == ["file exists"]
