from __future__ import annotations

import os
from dataclasses import dataclass

from agent_runtime.models.openai_compatible import (
    OpenAICompatibleProviderError,
    OpenAICompatibleSettings,
)


@dataclass(frozen=True)
class LocalProviderDefaults:
    provider: str
    base_url: str
    model_name: str | None
    api_key: str


LOCAL_PROVIDER_DEFAULTS = {
    "local": LocalProviderDefaults(
        provider="local",
        base_url="http://localhost:11434/v1",
        model_name=None,
        api_key="local",
    ),
    "ollama": LocalProviderDefaults(
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model_name="qwen2.5-coder:7b",
        api_key="ollama",
    ),
    "lmstudio": LocalProviderDefaults(
        provider="lmstudio",
        base_url="http://localhost:1234/v1",
        model_name=None,
        api_key="lmstudio",
    ),
    "vllm": LocalProviderDefaults(
        provider="vllm",
        base_url="http://localhost:8000/v1",
        model_name=None,
        api_key="vllm",
    ),
    "localai": LocalProviderDefaults(
        provider="localai",
        base_url="http://localhost:8080/v1",
        model_name=None,
        api_key="localai",
    ),
}


def local_provider_names() -> set[str]:
    return set(LOCAL_PROVIDER_DEFAULTS)


def local_settings_from_env(
    provider: str,
    env_prefix: str = "AGENT_MODEL",
) -> OpenAICompatibleSettings:
    defaults = LOCAL_PROVIDER_DEFAULTS[provider]
    model_name = _env(env_prefix, "NAME") or defaults.model_name
    if not model_name:
        raise OpenAICompatibleProviderError(
            f"{env_prefix}_NAME is required for local provider '{provider}'."
        )
    return OpenAICompatibleSettings(
        api_key=_env(env_prefix, "API_KEY") or defaults.api_key,
        base_url=(_env(env_prefix, "BASE_URL") or defaults.base_url).rstrip("/"),
        model_name=model_name,
        provider=provider,
        timeout_seconds=int(_env(env_prefix, "TIMEOUT_SECONDS", "180")),
        max_retries=int(_env(env_prefix, "MAX_RETRIES", "1")),
    )


def local_default_model(provider: str) -> str | None:
    return LOCAL_PROVIDER_DEFAULTS.get(provider, LOCAL_PROVIDER_DEFAULTS["local"]).model_name


def local_default_base_url(provider: str) -> str:
    return LOCAL_PROVIDER_DEFAULTS.get(provider, LOCAL_PROVIDER_DEFAULTS["local"]).base_url


def _env(env_prefix: str, key: str, default: str | None = None) -> str:
    value = os.getenv(f"{env_prefix}_{key}")
    if value is not None:
        return value
    if env_prefix != "AGENT_MODEL":
        value = os.getenv(f"AGENT_MODEL_{key}")
        if value is not None:
            return value
    return default or ""
