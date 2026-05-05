from __future__ import annotations

from agent_runtime.utils.time import now_iso


def build_model_failure_report(
    *,
    provider: str,
    model_name: str | None,
    base_url: str | None,
    error: Exception | str,
) -> dict:
    message = str(error)
    failure_type = classify_model_failure(message)
    return {
        "schema_version": "0.1.0",
        "provider": provider,
        "model_name": model_name,
        "base_url": base_url,
        "failure_type": failure_type,
        "retryable": failure_type in {"rate_limited", "server_error", "timeout", "network"},
        "summary": message,
        "recommendations": recommendations_for_failure(failure_type, provider),
        "created_at": now_iso(),
    }


def classify_model_failure(message: str) -> str:
    normalized = message.lower()
    if "api key" in normalized or "not configured" in normalized or "required" in normalized:
        return "configuration"
    if (
        "401" in normalized
        or "403" in normalized
        or "unauthorized" in normalized
        or "forbidden" in normalized
    ):
        return "authentication"
    if "429" in normalized or "rate limit" in normalized or "too many requests" in normalized:
        return "rate_limited"
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout"
    if "tls" in normalized or "ssl" in normalized or "eof" in normalized:
        return "network"
    if "http 5" in normalized or " 5" in normalized and "http" in normalized:
        return "server_error"
    if "budget" in normalized or "model call budget" in normalized:
        return "budget"
    if "json" in normalized or "choices" in normalized or "message.content" in normalized:
        return "provider_response"
    return "unknown"


def recommendations_for_failure(failure_type: str, provider: str) -> list[str]:
    if failure_type == "configuration":
        return [
            "Set the provider API key and model name environment variables.",
            "Run `agent model-check --skip-call` before spending model calls.",
        ]
    if failure_type == "authentication":
        return [
            "Verify the API key belongs to the selected provider and region.",
            "Rotate the key if it was revoked or copied incorrectly.",
        ]
    if failure_type == "rate_limited":
        return [
            "Retry later or reduce concurrent model calls.",
            "Route non-critical work to a cheap/local provider.",
        ]
    if failure_type == "server_error":
        return [
            "Retry with the configured finite retry policy.",
            "Temporarily route work to another provider if failures persist.",
        ]
    if failure_type == "timeout":
        return [
            "Increase AGENT_MODEL_TIMEOUT_SECONDS for slow providers.",
            "Retry or route the task to a local/offline provider.",
        ]
    if failure_type == "network":
        return [
            "Check network/TLS connectivity to the provider endpoint.",
            "Retry after transient network issues or use a local provider.",
        ]
    if failure_type == "budget":
        return [
            "Compact context before continuing.",
            "Reduce task count or ask for budget approval.",
        ]
    if failure_type == "provider_response":
        return [
            "Inspect the raw provider response shape.",
            "Use a model that supports JSON-mode or keep schema repair enabled.",
        ]
    return [
        f"Inspect provider `{provider}` logs and model call records.",
        "If the issue repeats, create a DecisionPoint for provider fallback.",
    ]
