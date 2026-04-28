import json

from agent_runtime.models.base import ChatMessage, ChatRequest
from agent_runtime.models.fake import FakeModelClient


def test_fake_model_returns_goal_spec_json() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[
                ChatMessage(role="user", content="User goal:\nmake a thing\n\nProject context:\n{}")
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["goal_id"] == "goal-0001"
    assert payload["original_goal"] == "make a thing"
    assert payload["expanded_requirements"][0]["description"]
    assert response.model_provider == "fake"


def test_fake_model_returns_execution_action_for_task() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="task_execution",
            model_tier="medium",
            messages=[
                ChatMessage(
                    role="user",
                    content=json.dumps({"task": {"task_id": "task-0001"}}),
                )
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["task_id"] == "task-0001"
    assert payload["tool_calls"][0]["tool_name"] == "write_file"
