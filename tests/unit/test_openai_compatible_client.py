from pathlib import Path

import pytest

from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ChatMessage, ChatRequest
from agent_runtime.models.http_transport import HttpResponse
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.models.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleProviderError,
    OpenAICompatibleSettings,
)
from agent_runtime.storage.schema_validator import SchemaValidator


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
    ) -> HttpResponse:
        self.calls.append(
            {"url": url, "headers": headers, "payload": payload, "timeout_seconds": timeout_seconds}
        )
        return self.response


def request() -> ChatRequest:
    return ChatRequest(
        purpose="planning",
        model_tier="strong",
        messages=[ChatMessage(role="user", content="Plan this.")],
        response_format="json",
        max_output_tokens=100,
    )


def policy(max_model_calls: int = 10) -> dict:
    return {
        "budgets": {
            "max_model_calls_per_goal": max_model_calls,
            "max_tool_calls_per_goal": 120,
            "max_total_minutes_per_goal": 30,
            "max_iterations_per_goal": 8,
            "max_repair_attempts_total": 5,
            "max_repair_attempts_per_task": 2,
            "max_replans_per_task": 2,
            "max_research_calls": 5,
            "max_user_decisions": 5,
        }
    }


def test_openai_compatible_client_sends_chat_request_and_logs_success(tmp_path: Path) -> None:
    transport = FakeTransport(
        HttpResponse(
            200,
            {
                "model": "test-model",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            },
        )
    )
    client = OpenAICompatibleClient(
        OpenAICompatibleSettings(
            api_key="test-key",
            base_url="https://example.test/v1",
            model_name="test-model",
        ),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=BudgetController(policy(), run_id="run-1"),
    )

    response = client.chat(request())

    assert response.content == '{"ok": true}'
    assert transport.calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert transport.calls[0]["payload"]["response_format"] == {"type": "json_object"}
    assert (tmp_path / "model_calls.jsonl").exists()


def test_openai_compatible_client_budget_denies_before_http_call(tmp_path: Path) -> None:
    transport = FakeTransport(HttpResponse(200, {}))
    client = OpenAICompatibleClient(
        OpenAICompatibleSettings(
            api_key="test-key",
            base_url="https://example.test/v1",
            model_name="test-model",
        ),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=BudgetController(policy(max_model_calls=0), run_id="run-1"),
    )

    with pytest.raises(OpenAICompatibleProviderError):
        client.chat(request())

    assert transport.calls == []
