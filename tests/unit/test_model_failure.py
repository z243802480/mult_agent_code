from __future__ import annotations

from agent_runtime.models.model_failure import (
    build_model_failure_report,
    classify_model_failure,
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
