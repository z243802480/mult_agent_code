from pathlib import Path

import pytest

from agent_runtime.models.base import ChatMessage, ChatRequest
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.fake import FakeModelClient
from agent_runtime.models.openai_compatible import OpenAICompatibleClient
from agent_runtime.models.routing import RoutedModelClient
from agent_runtime.storage.schema_validator import SchemaValidator


def request(model_tier: str) -> ChatRequest:
    return ChatRequest(
        purpose="routing-test",
        model_tier=model_tier,
        messages=[ChatMessage(role="user", content="hello")],
    )


@pytest.fixture(autouse=True)
def clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [
        "AGENT_MODEL_PROVIDER",
        "AGENT_MODEL_API_KEY",
        "AGENT_MODEL_BASE_URL",
        "AGENT_MODEL_NAME",
        "AGENT_MODEL_STRONG_PROVIDER",
        "AGENT_MODEL_STRONG_API_KEY",
        "AGENT_MODEL_STRONG_BASE_URL",
        "AGENT_MODEL_STRONG_NAME",
        "AGENT_MODEL_MEDIUM_PROVIDER",
        "AGENT_MODEL_MEDIUM_API_KEY",
        "AGENT_MODEL_MEDIUM_BASE_URL",
        "AGENT_MODEL_MEDIUM_NAME",
        "AGENT_MODEL_CHEAP_PROVIDER",
        "AGENT_MODEL_CHEAP_API_KEY",
        "AGENT_MODEL_CHEAP_BASE_URL",
        "AGENT_MODEL_CHEAP_NAME",
        "ZHIPU_API_KEY",
        "BIGMODEL_API_KEY",
        "ZAI_API_KEY",
        "GLM_API_KEY",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_factory_keeps_single_provider_when_no_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, FakeModelClient)


def test_factory_routes_configured_model_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "qwen2.5-coder:7b")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, RoutedModelClient)
    assert client.route_for_tier("strong").provider == "ollama"  # type: ignore[union-attr]
    assert isinstance(client.client_for_tier("strong"), OpenAICompatibleClient)
    assert isinstance(client.client_for_tier("medium"), FakeModelClient)
    assert isinstance(client.client_for_tier("cheap"), FakeModelClient)


def test_factory_can_use_tier_route_without_global_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "fake")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, RoutedModelClient)
    response = client.chat(request("medium"))
    assert response.model_provider == "fake"


def test_tier_specific_openai_settings_do_not_leak_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "strong-key")
    monkeypatch.setenv("AGENT_MODEL_STRONG_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "strong-model")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, RoutedModelClient)
    strong_client = client.client_for_tier("strong")
    assert isinstance(strong_client, OpenAICompatibleClient)
    assert strong_client.settings.api_key == "strong-key"
    assert strong_client.settings.base_url == "http://127.0.0.1:9999/v1"
    assert strong_client.settings.model_name == "strong-model"
    assert isinstance(client.client_for_tier("medium"), FakeModelClient)


def test_factory_routes_glm_as_strong_and_minimax_as_worker_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "zai")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-route-key")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-worker-key")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, RoutedModelClient)
    strong_client = client.client_for_tier("strong")
    medium_client = client.client_for_tier("medium")
    assert isinstance(strong_client, OpenAICompatibleClient)
    assert strong_client.provider == "zai"
    assert strong_client.settings.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert strong_client.settings.model_name == "glm-5.1"
    assert client.route_for_tier("strong").provider == "zai"  # type: ignore[union-attr]
    assert getattr(medium_client, "provider", None) == "minimax"


def test_factory_supports_zhipu_alias_with_bigmodel_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "zhipu")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, OpenAICompatibleClient)
    assert client.provider == "zhipu"
    assert client.settings.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert client.settings.model_name == "glm-5.1"
