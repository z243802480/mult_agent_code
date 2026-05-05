from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.models.model_failure import (
    ModelFailureRecorder,
    build_model_failure_report,
    classify_model_failure,
    model_failure_context_from_env,
)


def test_classify_model_failure_common_provider_errors() -> None:
    assert classify_model_failure("API key is not configured") == "configuration"
    assert classify_model_failure("HTTP 401 unauthorized") == "authentication"
    assert classify_model_failure("HTTP 429 rate limit") == "rate_limited"
    assert classify_model_failure("request timed out") == "timeout"
    assert classify_model_failure("TLS EOF while reading") == "network"
    assert classify_model_failure("HTTP 503: unavailable") == "server_error"
    assert classify_model_failure("model call budget exceeded") == "budget"
    assert classify_model_failure("response did not include choices") == "provider_response"


def test_build_model_failure_report_includes_recommendations() -> None:
    report = build_model_failure_report(
        provider="minimax",
        model_name="MiniMax-M2.7",
        base_url="https://api.minimax.io/v1",
        error="HTTP 429 rate limit",
    )

    assert report["failure_type"] == "rate_limited"
    assert report["retryable"] is True
    assert report["recommendations"]


def test_model_failure_recorder_writes_report_and_memory(tmp_path: Path) -> None:
    report_path, report = ModelFailureRecorder(tmp_path).record(
        provider="minimax",
        model_name="MiniMax-M2.7",
        base_url="https://api.minimaxi.com/v1",
        error="HTTP 503 unavailable",
    )

    assert report_path == tmp_path / ".agent" / "model" / "latest_failure.json"
    assert report_path.exists()
    assert report["failure_type"] == "server_error"

    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["failure_type"] == "server_error"

    memories = [
        json.loads(line)
        for line in (tmp_path / ".agent" / "memory" / "failures.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert memories[0]["type"] == "failure_lesson"
    assert memories[0]["source"]["kind"] == "model_failure_report"
    assert memories[0]["source"]["failure_type"] == "server_error"


def test_model_failure_context_uses_minimax_china_base_url_for_cp_keys(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "sk-cp-test")
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)

    context = model_failure_context_from_env()

    assert context.provider == "minimax"
    assert context.model_name == "MiniMax-M2.7"
    assert context.base_url == "https://api.minimaxi.com/v1"
