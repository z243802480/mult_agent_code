import json
from pathlib import Path

from agent_runtime.commands.model_check_command import ModelCheckCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakeHealthyClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert request.response_format == "json"
        assert request.purpose == "model_check"
        return ChatResponse(
            content=json.dumps({"ok": True}),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


class FakeBadJsonClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="not json",
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


def test_model_check_calls_model_and_accepts_valid_json(tmp_path: Path) -> None:
    result = ModelCheckCommand(tmp_path, model_client=FakeHealthyClient()).run()

    assert result.config_ok
    assert result.call_ok
    assert result.provider == "fake"
    assert result.model_name == "fake-model"


def test_model_check_can_skip_call_with_injected_client(tmp_path: Path) -> None:
    result = ModelCheckCommand(tmp_path, skip_call=True, model_client=FakeHealthyClient()).run()

    assert result.config_ok
    assert not result.call_ok
    assert "skipped" in result.summary


def test_model_check_reports_invalid_json_response(tmp_path: Path) -> None:
    result = ModelCheckCommand(tmp_path, model_client=FakeBadJsonClient()).run()

    assert result.config_ok
    assert not result.call_ok
    assert "failed" in result.summary.lower()


def test_model_check_reports_missing_provider_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODEL_NAME", "test-model")

    result = ModelCheckCommand(tmp_path).run()

    assert not result.config_ok
    assert not result.call_ok
    assert "api key" in result.summary.lower()
