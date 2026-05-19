import json
from pathlib import Path

import pytest

from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.local_route_config import (
    configured_route_tiers,
    local_route_value,
)
from asteria_runtime.models.openai_compatible import OpenAICompatibleClient
from asteria_runtime.models.route_diagnostics import route_diagnostic_for_tier
from asteria_runtime.models.routing import RoutedModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_loads_user_ps1_route_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "asteria-home"
    home.mkdir()
    (home / "model.routes.local.ps1").write_text(
        '\n'.join(
            [
                '$env:AGENT_MODEL_STRONG_PROVIDER = "glm"',
                '$env:AGENT_MODEL_STRONG_BASE_URL = "https://example.invalid/v1"',
                '$env:AGENT_MODEL_STRONG_NAME = "glm-4.7"',
                '$env:AGENT_MODEL_STRONG_API_KEY = "test-key"',
                '$env:AGENT_MODEL_STRONG_STREAMING = "1"',
                '$env:AGENT_MODEL_STRONG_STREAM_IDLE_TIMEOUT_SECONDS = "15"',
                '$env:AGENT_MODEL_MEDIUM_PROVIDER = "fake"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTERIA_HOME", str(home))

    assert configured_route_tiers() == {"strong", "medium"}
    assert local_route_value("AGENT_MODEL_STRONG", "API_KEY") == "test-key"

    diagnostic = route_diagnostic_for_tier("strong")
    assert diagnostic.configured is True
    assert diagnostic.source == "local_tier"
    assert diagnostic.api_key_present is True
    assert diagnostic.streaming_enabled is True
    assert diagnostic.stream_idle_timeout_seconds == 15


def test_environment_overrides_user_route_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "asteria-home"
    home.mkdir()
    (home / "model.routes.local.ps1").write_text(
        '$env:AGENT_MODEL_STRONG_PROVIDER = "fake"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTERIA_HOME", str(home))
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "qwen2.5-coder:7b")

    diagnostic = route_diagnostic_for_tier("strong")

    assert diagnostic.provider == "ollama"
    assert diagnostic.source == "tier"


def test_factory_uses_user_route_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "asteria-home"
    home.mkdir()
    (home / "model.routes.local.json").write_text(
        json.dumps(
            {
                "routes": {
                    "strong": {
                        "provider": "openai-compatible",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-model",
                        "api_key": "test-key",
                        "streaming": True,
                    },
                    "medium": {"provider": "fake"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTERIA_HOME", str(home))

    client = create_model_client(None, SchemaValidator(Path("schemas")))

    assert isinstance(client, RoutedModelClient)
    strong_client = client.client_for_tier("strong")
    assert isinstance(strong_client, OpenAICompatibleClient)
    assert strong_client.settings.api_key == "test-key"
    assert strong_client.settings.streaming_enabled is True
