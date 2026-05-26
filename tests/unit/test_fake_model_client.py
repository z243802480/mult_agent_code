import json
from pathlib import Path

from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator


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


def test_fake_model_records_runtime_user_progress(tmp_path: Path) -> None:
    client = FakeModelClient(logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))))

    client.chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[
                ChatMessage(role="user", content="User goal:\nmake a thing\n\nProject context:\n{}")
            ],
            response_format="json",
            metadata={
                "run_id": "run-1",
                "agent_id": "GoalSpecAgent",
                "agent_role_contract": {
                    "role": "GoalSpecAgent",
                    "purpose": "goal_spec",
                    "deadline_profile": "strong_goal_spec",
                    "provider_call_seconds": 42,
                    "stream_idle_timeout_seconds": 7,
                    "max_model_calls": 1,
                },
            },
        )
    )

    events = [
        json.loads(line)
        for line in (tmp_path / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(event["channel"], event["event_type"]) for event in events] == [
        ("model", "start"),
        ("model", "delta"),
        ("model", "end"),
    ]
    assert events[0]["phase"] == "plan"
    assert events[0]["telemetry"]["role"] == "GoalSpecAgent"
    assert events[0]["telemetry"]["deadline_ms"] == 42000
    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["agent_role"] == "GoalSpecAgent"
    assert logged["deadline_profile"] == "strong_goal_spec"
    assert logged["deadline_ms"] == 42000
