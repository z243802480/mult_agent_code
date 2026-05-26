import json
from pathlib import Path

import pytest

from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.http_transport import HttpTransport, HttpTransportError
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeResponse:
    status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""


class FakeStreamResponse:
    status = 200

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(
            [
                b'data: {"model":"stream-model","choices":[{"delta":{"content":"{\\"ok\\""},"finish_reason":null}]}\n\n',
                b'data: {"choices":[{"delta":{"content":": true}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n',
                b"data: [DONE]\n\n",
            ]
        )


def test_http_transport_reports_success_status_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(HttpTransportError, match="non-JSON body"):
        HttpTransport().post_json(
            "https://example.test/v1/chat/completions",
            headers={},
            payload={"ok": True},
            timeout_seconds=1,
        )


def test_http_transport_parses_openai_style_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeStreamResponse:
        return FakeStreamResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = HttpTransport().post_json_stream(
        "https://example.test/v1/chat/completions",
        headers={},
        payload={"stream": True},
        timeout_seconds=5,
        idle_timeout_seconds=2,
        deadline_seconds=5,
    )

    assert response.body["choices"][0]["message"]["content"] == '{"ok": true}'
    assert response.body["usage"]["total_tokens"] == 3
    assert response.telemetry.requested is True
    assert response.telemetry.chunk_count == 2
    assert response.telemetry.idle_timeout_ms == 2000


def test_http_transport_stream_writes_studio_model_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeStreamResponse:
        return FakeStreamResponse()

    event_file = tmp_path / "events.jsonl"
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ASTERIA_STUDIO_EVENT_SINK", str(event_file))
    monkeypatch.setenv("ASTERIA_STUDIO_SESSION_ID", "session-test")

    HttpTransport().post_json_stream(
        "https://api.minimax.io/v1/chat/completions",
        headers={},
        payload={"stream": True, "model": "MiniMax-M2.7"},
        timeout_seconds=5,
        idle_timeout_seconds=2,
        deadline_seconds=5,
    )

    events = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in events] == [
        "model_start",
        "model_delta",
        "model_delta",
        "model_end",
    ]
    assert "".join(event.get("content_delta", "") for event in events) == '{"ok": true}'
    assert events[0]["model_provider"] == "minimax"
    assert events[-1]["telemetry"]["chunk_count"] == 2


def test_http_transport_stream_writes_runtime_user_progress_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeStreamResponse:
        return FakeStreamResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    request = ChatRequest(
        purpose="task_execution",
        model_tier="medium",
        messages=[ChatMessage(role="user", content="do work")],
        metadata={
            "run_id": "run-1",
            "agent_id": "CoderAgent",
            "runtime_profile_id": "runtime-profile-task-0001",
            "model_profile_id": "model-profile-task-0001",
            "task_id": "task-0001",
            "agent_role_contract": {
                "role": "CoderAgent",
                "purpose": "coding",
                "deadline_profile": "worker",
                "provider_call_seconds": 5,
                "stream_idle_timeout_seconds": 2,
                "max_model_calls": 1,
            },
        },
    )
    logger = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas")))

    with logger.progress_context(request):
        HttpTransport().post_json_stream(
            "https://api.minimax.io/v1/chat/completions",
            headers={},
            payload={"stream": True, "model": "MiniMax-M2.7"},
            timeout_seconds=5,
            idle_timeout_seconds=2,
            deadline_seconds=5,
        )

    events = [
        json.loads(line)
        for line in (tmp_path / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(event["channel"], event["event_type"]) for event in events] == [
        ("model", "start"),
        ("model", "delta"),
        ("model", "delta"),
        ("model", "end"),
    ]
    assert "".join(event.get("content_delta", "") for event in events) == '{"ok": true}'
    assert events[0]["phase"] == "execute"
    assert events[0]["model_provider"] == "minimax"
    assert events[0]["telemetry"]["role"] == "CoderAgent"
    assert events[0]["telemetry"]["deadline_profile"] == "worker"
    assert events[0]["telemetry"]["deadline_ms"] == 5000
    assert events[0]["telemetry"]["provider_call_seconds"] == 5
    assert events[0]["data"]["agent_role_contract"]["role"] == "CoderAgent"
    assert events[1]["telemetry"]["deadline_remaining_ms"] <= 5000
    assert events[-1]["telemetry"]["chunk_count"] == 2
    assert events[-1]["telemetry"]["role"] == "CoderAgent"
