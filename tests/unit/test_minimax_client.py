from pathlib import Path
import json

import pytest

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.http_transport import HttpResponse, HttpTransportError
from asteria_runtime.models.minimax import (
    MiniMaxOpenAICompatibleClient,
    MiniMaxSettings,
    ModelProviderError,
    default_minimax_base_url,
)
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post_json(
        self, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int
    ) -> HttpResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class FakeStreamingTransport(FakeTransport):
    def post_json_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
        idle_timeout_seconds: int,
        deadline_seconds: int | None = None,
    ):
        from asteria_runtime.models.base import StreamingTelemetry
        from asteria_runtime.models.http_transport import HttpStreamingResponse

        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "idle_timeout_seconds": idle_timeout_seconds,
                "deadline_seconds": deadline_seconds,
            }
        )
        return HttpStreamingResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                "base_resp": {"status_code": 0, "status_msg": ""},
            },
            StreamingTelemetry(
                requested=True,
                supported=True,
                mode="streaming",
                first_chunk_ms=35,
                last_chunk_ms=70,
                duration_ms=90,
                chunk_count=2,
                idle_timeout_ms=30000,
                deadline_ms=90000,
                finish_reason="stop",
            ),
        )


class FakeUnsupportedStreamingTransport(FakeTransport):
    def __init__(self, response: HttpResponse, fallback_response: HttpResponse) -> None:
        super().__init__(fallback_response)
        self.stream_response = response

    def post_json_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
        idle_timeout_seconds: int,
        deadline_seconds: int | None = None,
    ):
        from asteria_runtime.models.base import StreamingTelemetry
        from asteria_runtime.models.http_transport import HttpStreamingResponse

        self.calls.append(
            {
                "kind": "stream",
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "idle_timeout_seconds": idle_timeout_seconds,
                "deadline_seconds": deadline_seconds,
            }
        )
        return HttpStreamingResponse(
            self.stream_response.status_code,
            self.stream_response.body,
            StreamingTelemetry(
                requested=True,
                supported=False,
                mode="streaming_failed",
                duration_ms=1,
                error_type="http_error",
            ),
        )

    def post_json(
        self, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int
    ) -> HttpResponse:
        self.calls.append(
            {
                "kind": "http",
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class FakeBrokenStreamingTransport(FakeTransport):
    def post_json_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
        idle_timeout_seconds: int,
        deadline_seconds: int | None = None,
    ):
        self.calls.append(
            {
                "kind": "stream",
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "idle_timeout_seconds": idle_timeout_seconds,
                "deadline_seconds": deadline_seconds,
            }
        )
        raise HttpTransportError("<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred>")

    def post_json(
        self, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int
    ) -> HttpResponse:
        self.calls.append(
            {
                "kind": "http",
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class AlwaysFailingTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__(HttpResponse(500, {}))

    def post_json(
        self, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int
    ) -> HttpResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        raise HttpTransportError("request timed out")


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


def role_deadline_request() -> ChatRequest:
    return ChatRequest(
        purpose="task_execution",
        model_tier="medium",
        messages=[ChatMessage(role="user", content="Do this.")],
        metadata={
            "agent_role_contract": {
                "role": "CoderAgent",
                "purpose": "coding",
                "deadline_profile": "worker",
                "provider_call_seconds": 42,
                "stream_idle_timeout_seconds": 7,
                "max_model_calls": 1,
            }
        },
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


def test_minimax_client_sends_openai_compatible_chat_and_logs_success(tmp_path: Path) -> None:
    transport = FakeTransport(
        HttpResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
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
        MiniMaxSettings(api_key="test-key", model_name="MiniMax-M2.7", streaming_enabled=False),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=BudgetController(policy(), run_id="run-1"),
    )

    response = client.chat(request())

    assert response.content == '{"ok": true}'
    assert response.usage.input_tokens == 12
    assert transport.calls[0]["url"] == "https://api.minimax.io/v1/chat/completions"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert transport.calls[0]["payload"]["response_format"] == {"type": "json_object"}
    assert (tmp_path / "model_calls.jsonl").exists()
    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["streaming"]["mode"] == "non_streaming"


def test_minimax_client_streams_by_default_and_logs_first_chunk(tmp_path: Path) -> None:
    transport = FakeStreamingTransport(HttpResponse(200, {}))
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key"),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
    )

    response = client.chat(request())

    assert response.content == '{"ok": true}'
    assert response.streaming is not None
    assert response.streaming.first_chunk_ms == 35
    assert transport.calls[0]["payload"]["stream"] is True
    assert transport.calls[0]["payload"]["stream_options"] == {"include_usage": True}
    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["streaming"]["requested"] is True
    assert logged["streaming"]["chunk_count"] == 2


def test_minimax_client_uses_role_deadline_for_provider_call() -> None:
    transport = FakeStreamingTransport(HttpResponse(200, {}))
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(
            api_key="test-key",
            timeout_seconds=90,
            stream_idle_timeout_seconds=30,
        ),
        transport=transport,
    )

    client.chat(role_deadline_request())

    assert transport.calls[0]["timeout_seconds"] == 42
    assert transport.calls[0]["idle_timeout_seconds"] == 7
    assert transport.calls[0]["deadline_seconds"] == 42


def test_minimax_client_shares_role_deadline_across_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr("asteria_runtime.models.minimax.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "asteria_runtime.models.minimax.time.sleep",
        lambda seconds: clock.update(now=clock["now"] + float(seconds)),
    )
    transport = AlwaysFailingTransport()
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key", max_retries=2, streaming_enabled=False),
        transport=transport,
    )

    with pytest.raises(ModelProviderError):
        client.chat(role_deadline_request())

    assert [call["timeout_seconds"] for call in transport.calls] == [42, 41, 38]


def test_minimax_client_falls_back_when_streaming_is_unsupported(tmp_path: Path) -> None:
    transport = FakeUnsupportedStreamingTransport(
        HttpResponse(400, {"error": {"message": "streaming is not supported by this model"}}),
        HttpResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                "base_resp": {"status_code": 0, "status_msg": ""},
            },
        ),
    )
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key"),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
    )

    response = client.chat(request())

    assert response.content == '{"ok": true}'
    assert len(transport.calls) == 2
    assert transport.calls[0]["payload"]["stream"] is True
    assert transport.calls[1]["payload"]["stream"] is False
    assert "stream_options" not in transport.calls[1]["payload"]
    assert response.streaming is not None
    assert response.streaming.mode == "streaming_fallback_non_streaming"
    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["streaming"]["error_type"] == "streaming_unsupported"


def test_minimax_client_falls_back_on_stream_setup_error(tmp_path: Path) -> None:
    transport = FakeBrokenStreamingTransport(
        HttpResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                "base_resp": {"status_code": 0, "status_msg": ""},
            },
        )
    )
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key"),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
    )

    response = client.chat(request())

    assert response.content == '{"ok": true}'
    assert len(transport.calls) == 2
    assert transport.calls[1]["payload"]["stream"] is False
    assert response.streaming is not None
    assert response.streaming.mode == "streaming_fallback_non_streaming"
    assert response.streaming.error_type == "streaming_transport_error"


def test_minimax_client_raises_and_logs_http_failure(tmp_path: Path) -> None:
    transport = FakeTransport(HttpResponse(401, {"error": {"message": "unauthorized"}}))
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="bad-key", max_retries=0, streaming_enabled=False),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
    )

    with pytest.raises(ModelProviderError):
        client.chat(request())

    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["status"] == "failure"
    assert logged["streaming"]["mode"] == "non_streaming_failed"


def test_minimax_client_budget_denies_before_http_call(tmp_path: Path) -> None:
    transport = FakeTransport(HttpResponse(200, {}))
    budget = BudgetController(policy(max_model_calls=0), run_id="run-1")
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key", streaming_enabled=False),
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


def test_minimax_client_feeds_usage_truth_back_into_context_pressure(tmp_path: Path) -> None:
    # S90 regression: the real minimax path must fold usage truth into pressure/calibration
    # (wiring only in metered.py never runs in production).
    transport = FakeTransport(
        HttpResponse(
            200,
            {
                "model": "MiniMax-M2.7",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 800, "completion_tokens": 5, "total_tokens": 805},
                "base_resp": {"status_code": 0, "status_msg": ""},
            },
        )
    )
    small_window_policy = policy()
    small_window_policy["context"] = {"model_context_windows": {"minimax": 1000}}
    budget = BudgetController(small_window_policy, run_id="run-1")
    client = MiniMaxOpenAICompatibleClient(
        MiniMaxSettings(api_key="test-key", model_name="MiniMax-M2.7", streaming_enabled=False),
        transport=transport,
        logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))),
        budget=budget,
    )

    client.chat(request())

    assert budget.usage.context_window_tokens == 1000
    assert budget.usage.latest_observed_prompt_tokens == 800
    assert budget.usage.context_estimate_calibration != 1.0
