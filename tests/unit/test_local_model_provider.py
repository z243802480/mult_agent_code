from pathlib import Path

import pytest

from agent_runtime.models.factory import create_model_client
from agent_runtime.models.local import (
    local_default_base_url,
    local_default_model,
    local_provider_names,
    local_settings_from_env,
)
from agent_runtime.models.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleProviderError,
)
from agent_runtime.storage.schema_validator import SchemaValidator


def test_local_provider_defaults_cover_common_openai_compatible_servers() -> None:
    assert {"local", "ollama", "lmstudio", "vllm", "localai"} <= local_provider_names()
    assert local_default_base_url("ollama") == "http://localhost:11434/v1"
    assert local_default_base_url("lmstudio") == "http://localhost:1234/v1"
    assert local_default_base_url("vllm") == "http://localhost:8000/v1"
    assert local_default_model("ollama") == "qwen2.5-coder:7b"


def test_ollama_provider_can_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "ollama")
    monkeypatch.delenv("AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_NAME", raising=False)

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, OpenAICompatibleClient)
    assert client.settings.provider == "ollama"
    assert client.settings.base_url == "http://localhost:11434/v1"
    assert client.settings.model_name == "qwen2.5-coder:7b"
    assert client.settings.api_key == "ollama"


def test_local_provider_requires_model_name_when_no_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_MODEL_NAME", raising=False)

    with pytest.raises(OpenAICompatibleProviderError):
        local_settings_from_env("lmstudio")


def test_local_provider_accepts_custom_endpoint_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_NAME", "local-coder")
    monkeypatch.setenv("AGENT_MODEL_BASE_URL", "http://127.0.0.1:9999/v1/")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "custom-local")

    settings = local_settings_from_env("local")

    assert settings.provider == "local"
    assert settings.base_url == "http://127.0.0.1:9999/v1"
    assert settings.model_name == "local-coder"
    assert settings.api_key == "custom-local"
