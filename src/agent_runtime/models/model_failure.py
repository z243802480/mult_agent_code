from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.models.local import (
    local_default_base_url,
    local_default_model,
    local_provider_names,
)
from agent_runtime.models.minimax import default_minimax_base_url
from agent_runtime.models.routing import ModelRoute
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ModelFailureContext:
    provider: str
    model_name: str | None
    base_url: str | None


class ModelFailureRecorder:
    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(
            Path(__file__).resolve().parents[3] / "schemas"
        )
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def record(
        self,
        *,
        provider: str,
        model_name: str | None,
        base_url: str | None,
        error: Exception | str,
    ) -> tuple[Path, dict]:
        report = build_model_failure_report(
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            error=error,
        )
        path = self.root / ".agent" / "model" / "latest_failure.json"
        self.store.write(path, report, "model_failure_report")
        self._record_memory(report)
        return path, report

    def _record_memory(self, report: dict) -> None:
        path = self.root / ".agent" / "memory" / "failures.jsonl"
        existing = self.jsonl.read_all(path, "memory_entry")
        memory = {
            "schema_version": "0.1.0",
            "memory_id": f"memory-{len(existing) + 1:04d}",
            "type": "failure_lesson",
            "content": (
                f"Model provider `{report['provider']}` failed with `{report['failure_type']}`. "
                f"Summary: {report['summary']}"
            ),
            "source": {
                "kind": "model_failure_report",
                "provider": report["provider"],
                "model_name": report["model_name"],
                "base_url": report["base_url"],
                "failure_type": report["failure_type"],
            },
            "tags": ["model", "failure", f"provider:{report['provider']}", report["failure_type"]],
            "confidence": 0.8,
            "created_at": report["created_at"],
        }
        self.jsonl.append(path, memory, "memory_entry")


def model_failure_context_from_env(env_prefix: str = "AGENT_MODEL") -> ModelFailureContext:
    provider = (_env(env_prefix, "PROVIDER") or "minimax").lower()
    return ModelFailureContext(
        provider=provider,
        model_name=_env(env_prefix, "NAME") or _default_model(provider),
        base_url=_env(env_prefix, "BASE_URL") or _default_base_url(provider, env_prefix),
    )


def model_failure_context_from_client(
    client: object,
    *,
    model_tier: str,
    fallback_env_prefix: str = "AGENT_MODEL",
) -> ModelFailureContext:
    delegate = getattr(client, "delegate", None)
    if delegate is not None and delegate is not client:
        return model_failure_context_from_client(
            delegate,
            model_tier=model_tier,
            fallback_env_prefix=fallback_env_prefix,
        )
    route = _route_for_tier(client, model_tier)
    context = model_failure_context_from_env(route.env_prefix if route else fallback_env_prefix)
    provider = _client_provider(client) or (route.provider if route else None) or context.provider
    settings = getattr(client, "settings", None)
    model_name = getattr(settings, "model_name", None) or context.model_name
    base_url = getattr(settings, "base_url", None) or context.base_url
    return ModelFailureContext(provider=provider, model_name=model_name, base_url=base_url)


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


def _route_for_tier(client: object, model_tier: str) -> ModelRoute | None:
    route_for_tier = getattr(client, "route_for_tier", None)
    if not callable(route_for_tier):
        return None
    route = route_for_tier(model_tier)
    return route if isinstance(route, ModelRoute) else None


def _client_provider(client: object) -> str | None:
    provider = getattr(client, "provider", None)
    return str(provider).lower() if provider else None


def _default_model(provider: str) -> str | None:
    if provider == "minimax":
        return "MiniMax-M2.7"
    if provider in {"fake", "offline"}:
        return "fake-offline"
    if provider in local_provider_names():
        return local_default_model(provider)
    return None


def _default_base_url(provider: str, env_prefix: str) -> str | None:
    if provider in {"fake", "offline"}:
        return "local offline provider"
    if provider in local_provider_names():
        return local_default_base_url(provider)
    if provider == "minimax":
        return default_minimax_base_url(_env(env_prefix, "API_KEY"))
    if provider in {"openai", "openai-compatible", "generic"}:
        return "https://api.openai.com/v1"
    return None


def _env(env_prefix: str, key: str) -> str:
    value = os.getenv(f"{env_prefix}_{key}")
    if value is not None:
        return value
    if env_prefix != "AGENT_MODEL":
        value = os.getenv(f"AGENT_MODEL_{key}")
        if value is not None:
            return value
    return ""
