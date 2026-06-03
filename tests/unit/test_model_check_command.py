import json
from pathlib import Path

from asteria_runtime.commands.model_check_command import ModelCheckCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, StreamingTelemetry, TokenUsage


class FakeHealthyClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert request.response_format == "json"
        assert request.purpose == "model_check"
        assert request.temperature == 0.1
        assert request.max_output_tokens == 512
        assert request.metadata["agent_id"] == "ModelCheckAgent"
        assert request.metadata["agent_role_contract"]["role"] == "ModelCheckAgent"
        assert request.metadata["agent_role_contract"]["provider_call_seconds"] == 30
        return ChatResponse(
            content=json.dumps({"ok": True}),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
            streaming=StreamingTelemetry(
                requested=True,
                supported=True,
                mode="streaming",
                first_chunk_ms=10,
                last_chunk_ms=15,
                duration_ms=20,
                chunk_count=1,
            ),
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
    assert result.to_dict()["streaming"]["first_chunk_ms"] == 10
    assert "Streaming: streaming chunks=1" in result.to_text()


def test_model_check_records_route_check_evidence(tmp_path: Path) -> None:
    result = ModelCheckCommand(tmp_path, model_client=FakeHealthyClient()).run()

    path = tmp_path / ".asteria" / "model" / "model_route_checks.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert result.call_ok
    assert payload["tier"] == "cheap"
    assert payload["purpose"] == "model_check"
    assert payload["provider"] == "fake"
    assert payload["model_name"] == "fake-model"
    assert payload["status"] == "success"
    assert payload["streaming"]["first_chunk_ms"] == 10


def test_model_check_skip_call_does_not_record_route_check(tmp_path: Path) -> None:
    result = ModelCheckCommand(tmp_path, skip_call=True, model_client=FakeHealthyClient()).run()

    assert not result.call_ok
    assert not (tmp_path / ".asteria" / "model" / "model_route_checks.jsonl").exists()


def test_model_check_uses_requested_model_tier(tmp_path: Path) -> None:
    class TierClient:
        def chat(self, request: ChatRequest) -> ChatResponse:
            assert request.model_tier == "strong"
            assert request.metadata["agent_role_contract"]["provider_call_seconds"] == 120
            assert request.metadata["deadline_ms"] == 120000
            return ChatResponse(
                content=json.dumps({"ok": True}),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-strong",
                raw_response={},
            )

    result = ModelCheckCommand(tmp_path, model_tier="strong", model_client=TierClient()).run()

    assert result.call_ok
    assert result.model_name == "fake-strong"


def test_model_check_reports_route_fallback_from_response(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "sk-cp-test")

    class FallbackClient:
        def chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(
                content=json.dumps({"ok": True}),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="minimax",
                model_name="MiniMax-M2.7",
                raw_response={
                    "route_fallback": {
                        "used": True,
                        "from_tier": "strong",
                        "to_tier": "medium",
                        "policy": "strong_timeout_to_medium",
                    }
                },
            )

    result = ModelCheckCommand(
        tmp_path,
        model_tier="strong",
        model_client=FallbackClient(),
    ).run()

    payload = result.to_dict()
    assert result.call_ok
    assert payload["route_fallback"]["used"] is True
    assert result.base_url == "https://api.minimaxi.com/v1"
    assert "Call fallback: strong -> medium" in result.to_text()


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
        for line in (tmp_path / ".asteria" / "memory" / "failures.jsonl")
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
    assert "api_key" in result.summary.lower()
    assert result.failure_type == "configuration"
    assert result.failure_report_path is None
    payload = result.to_dict()
    assert payload["route_health"]["status"] == "blocked"
    assert payload["route_health"]["recommended_next_command"] == "model-check"
    assert "Route health: blocked" in result.to_text()


def test_model_check_route_health_matches_status_review_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "strong-model")
    monkeypatch.delenv("AGENT_MODEL_STRONG_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    payload = ModelCheckCommand(tmp_path, model_tier="strong").run().to_dict()
    validation = payload["route_health"]

    assert validation["status"] == "blocked"
    assert validation["routes"][0]["tier"] == "strong"
    assert validation["routes"][0]["provider"] == "openai-compatible"
    assert validation["routes"][0]["model_name"] == "strong-model"
    assert validation["routes"][0]["configured"] is False
    assert validation["current_blocker"] == validation["blockers"][0]
    assert validation["recommended_next_command"] == "model-check"


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


def test_model_check_reports_glm_default_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "glm")
    monkeypatch.delenv("AGENT_MODEL_NAME", raising=False)
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)

    result = ModelCheckCommand(tmp_path, skip_call=True, model_client=FakeHealthyClient()).run()

    assert result.provider == "glm"
    assert result.model_name == "glm-5.1"
    assert result.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"


def test_model_check_reports_tier_specific_glm_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.delenv("AGENT_MODEL_STRONG_NAME", raising=False)
    monkeypatch.delenv("AGENT_MODEL_STRONG_BASE_URL", raising=False)

    result = ModelCheckCommand(
        tmp_path,
        skip_call=True,
        model_tier="strong",
        model_client=FakeHealthyClient(),
    ).run()

    assert result.provider == "glm"
    assert result.model_name == "glm-5.1"
    assert result.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"


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
