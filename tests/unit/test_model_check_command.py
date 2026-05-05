import json
from pathlib import Path

from agent_runtime.commands.model_check_command import ModelCheckCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakeHealthyClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert request.response_format == "json"
        assert request.purpose == "model_check"
        assert request.temperature == 0.1
        assert request.max_output_tokens == 512
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
    assert result.failure_type == "provider_response"
    assert result.failure_report_path is not None
    report = json.loads(result.failure_report_path.read_text(encoding="utf-8"))
    assert report["failure_type"] == "provider_response"
    memories = [
        json.loads(line)
        for line in (tmp_path / ".agent" / "memory" / "failures.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert memories[0]["source"]["kind"] == "model_failure_report"
    assert memories[0]["source"]["failure_type"] == "provider_response"


def test_model_check_reports_missing_provider_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODEL_NAME", "test-model")

    result = ModelCheckCommand(tmp_path).run()

    assert not result.config_ok
    assert not result.call_ok
    assert "api key" in result.summary.lower()
    assert result.failure_type == "configuration"
    assert result.failure_report_path is not None


def test_model_check_reports_local_provider_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "ollama")
    monkeypatch.delenv("AGENT_MODEL_NAME", raising=False)
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)

    result = ModelCheckCommand(tmp_path, skip_call=True).run()

    assert result.config_ok
    assert result.provider == "ollama"
    assert result.model_name == "qwen2.5-coder:7b"
    assert result.base_url == "http://localhost:11434/v1"


def test_model_check_reports_minimax_current_openai_compatible_base_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)

    result = ModelCheckCommand(tmp_path, skip_call=True, model_client=FakeHealthyClient()).run()

    assert result.base_url == "https://api.minimax.io/v1"


def test_model_check_reports_minimax_china_base_url_for_cp_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "sk-cp-test")
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)

    result = ModelCheckCommand(tmp_path, skip_call=True, model_client=FakeHealthyClient()).run()

    assert result.base_url == "https://api.minimaxi.com/v1"


def test_model_check_classifies_call_failures(tmp_path: Path) -> None:
    class RateLimitedClient:
        def chat(self, request: ChatRequest) -> ChatResponse:
            raise RuntimeError("HTTP 429 rate limit")

    result = ModelCheckCommand(tmp_path, model_client=RateLimitedClient()).run()

    assert result.config_ok
    assert not result.call_ok
    assert result.failure_type == "rate_limited"
    assert result.failure_report_path is not None
    assert "Failure type: rate_limited" in result.to_text()
