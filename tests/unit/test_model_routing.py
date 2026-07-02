from pathlib import Path

import pytest

from asteria_runtime.models.base import ChatMessage, ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.openai_compatible import OpenAICompatibleClient
from asteria_runtime.models.route_resolver import resolve_model_route
from asteria_runtime.models.routing import ModelRoute, RoutedModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator


def request(model_tier: str) -> ChatRequest:
    return ChatRequest(
        purpose="routing-test",
        model_tier=model_tier,
        messages=[ChatMessage(role="user", content="hello")],
    )


class TimeoutClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError("stream deadline exceeded")


class CaptureClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content='{"ok": true}',
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model_provider="minimax",
            model_name="MiniMax-M2.7",
            raw_response={},
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


def test_routed_client_falls_back_from_strong_timeout_to_medium() -> None:
    medium = CaptureClient()
    client = RoutedModelClient(
        default_client=medium,
        tier_clients={"strong": TimeoutClient(), "medium": medium},
        routes={
            "strong": ModelRoute("strong", "glm", "AGENT_MODEL_STRONG"),
            "medium": ModelRoute("medium", "minimax", "AGENT_MODEL_MEDIUM"),
        },
    )

    response = client.chat(request("strong"))

    assert response.model_provider == "minimax"
    assert response.raw_response["route_fallback"]["used"] is True
    assert response.raw_response["route_fallback"]["from_tier"] == "strong"
    assert medium.requests[0].model_tier == "medium"
    assert medium.requests[0].metadata["route_fallback"]["policy"] == "strong_timeout_to_medium"


def test_routed_client_can_disable_strong_timeout_fallback() -> None:
    client = RoutedModelClient(
        default_client=FakeModelClient(),
        tier_clients={"strong": TimeoutClient(), "medium": FakeModelClient()},
        routes={
            "strong": ModelRoute("strong", "glm", "AGENT_MODEL_STRONG"),
            "medium": ModelRoute("medium", "minimax", "AGENT_MODEL_MEDIUM"),
        },
    )

    with pytest.raises(RuntimeError, match="stream deadline exceeded"):
        client.chat(
            ChatRequest(
                purpose="routing-test",
                model_tier="strong",
                messages=[ChatMessage(role="user", content="hello")],
                metadata={"disable_route_fallback": True},
            )
        )


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


def test_model_call_logger_persists_route_fallback(tmp_path: Path) -> None:
    from asteria_runtime.models.model_call_logger import ModelCallLogger
    from asteria_runtime.storage.jsonl_store import JsonlStore

    logger = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas")))
    fallback = {
        "used": True,
        "from_tier": "strong",
        "to_tier": "medium",
        "reason": "deadline exceeded",
        "policy": "strong_timeout_to_medium",
    }
    call = ChatRequest(
        purpose="chat",
        model_tier="medium",
        messages=[ChatMessage(role="user", content="hello")],
        metadata={"run_id": "run-1", "route_fallback": fallback},
    )
    response = ChatResponse(
        content="ok",
        finish_reason="stop",
        usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        model_provider="minimax",
        model_name="abab",
        raw_response={},
    )
    record = logger.record_success(call, response)

    assert record is not None and record["route_fallback"]["from_tier"] == "strong"
    rows = JsonlStore().read_all(tmp_path / "model_calls.jsonl")
    assert rows and rows[0]["route_fallback"]["policy"] == "strong_timeout_to_medium"


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
    assert strong_client.settings.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
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


def test_route_resolver_reports_missing_requirements_without_fake_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_NAME", "fallback-model")

    resolution = resolve_model_route("strong")

    assert resolution.configured is False
    assert resolution.provider == "openai-compatible"
    assert resolution.model_name == "fallback-model"
    assert "AGENT_MODEL_API_KEY or OPENAI_API_KEY" in resolution.missing
    assert "Configure model route requirements" in resolution.next_action


def test_route_resolver_uses_auditable_default_routes_when_route_missing() -> None:
    strong = resolve_model_route("strong")
    cheap = resolve_model_route("cheap")

    assert strong.provider == "glm"
    assert strong.model_name == "glm-5.1"
    assert strong.deadline_seconds == 120
    assert strong.fallback_used is True
    assert strong.fallback_source == "default_route_policy"
    assert "ZAI_API_KEY" in " ".join(str(item) for item in strong.missing)
    assert "No explicit env/local route" in (strong.fallback_reason or "")
    assert cheap.configured is True
    assert cheap.provider == "fake"
    assert cheap.model_name == "fake-offline"
    assert cheap.deadline_seconds == 30
    assert cheap.next_action.startswith("Using default route policy")
