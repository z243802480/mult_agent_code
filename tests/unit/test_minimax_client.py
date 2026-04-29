from pathlib import Path

import pytest

from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ChatMessage, ChatRequest
from agent_runtime.models.http_transport import HttpResponse
from agent_runtime.models.minimax import (
    MiniMaxOpenAICompatibleClient,
    MiniMaxSettings,
    ModelProviderError,
    default_minimax_base_url,
)
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.schema_validator import SchemaValidator


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post_json(self, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int) -> HttpResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def request() -> ChatRequest:
    return ChatRequest(
        purpose="planning",
        model_tier="strong",
        messages=[
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Plan this."),
        ],
        response_format="json",
        temperature=0.2,
        max_output_tokens=100,
        metadata={"run_id": "run-1", "agent_id": "agent-1"},
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
            "max_research_calls": 5,
            "max_user_decisions": 5,
        }
    }


def test_minimax_client_sends_openai_compatible_chat_and_logs_success(tmp_path: Path) -> None:
    transport = FakeTransport(
        HttpResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "{\"ok\": true}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                },
                "base_resp": {"status_code": 0, "status_msg": ""},
            },
        )
    )
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key", model_name="MiniMax-M2.7"),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=BudgetController(policy(), run_id="run-1"),
    )

    response = client.chat(request())

    assert response.content == "{\"ok\": true}"
    assert response.usage.input_tokens == 12
    assert transport.calls[0]["url"] == "https://api.minimax.io/v1/chat/completions"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert transport.calls[0]["payload"]["response_format"] == {"type": "json_object"}
    assert (tmp_path / "model_calls.jsonl").exists()


def test_minimax_client_raises_and_logs_http_failure(tmp_path: Path) -> None:
    transport = FakeTransport(HttpResponse(401, {"error": {"message": "unauthorized"}}))
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="bad-key", max_retries=0),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
    )

    with pytest.raises(ModelProviderError):
        client.chat(request())

    assert (tmp_path / "model_calls.jsonl").read_text(encoding="utf-8")


def test_minimax_client_budget_denies_before_http_call(tmp_path: Path) -> None:
    transport = FakeTransport(HttpResponse(200, {}))
    budget = BudgetController(policy(max_model_calls=0), run_id="run-1")
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key"),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=budget,
    )

    with pytest.raises(ModelProviderError):
        client.chat(request())

    assert transport.calls == []


def test_minimax_default_base_url_follows_key_region() -> None:
    assert default_minimax_base_url("sk-cp-example") == "https://api.minimaxi.com/v1"
    assert default_minimax_base_url("sk-global-example") == "https://api.minimax.io/v1"
