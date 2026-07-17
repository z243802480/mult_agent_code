"""G8-b: a run may pin which model each tier asks for, via its own run_config.json.

Which model backs a tier is otherwise resolved from env / the local route file, so a Studio or CLI
choice could never reach it. The pin swaps ONLY the model name, keeping that tier's configured
provider, base URL and API key — it can never point a tier at a provider whose credentials are not
configured. Reading the pin from run_config (rather than a constructor argument) is what makes it
survive resume, the same way the permission tier does.
"""

import os
from pathlib import Path

import pytest

from asteria_runtime.core.run_config import normalize_model_name_overrides, write_run_config
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.fixture()
def _clean_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ambient route env so resolution is deterministic on any developer machine."""
    for key in list(os.environ):
        if key.startswith("AGENT_MODEL") or key in {
            "MINIMAX_API_KEY",
            "MINIMAX_CN_API_KEY",
            "ZAI_API_KEY",
            "GLM_API_KEY",
            "ZHIPU_API_KEY",
            "BIGMODEL_API_KEY",
            "OPENAI_API_KEY",
        }:
            monkeypatch.delenv(key, raising=False)
    # An unset ASTERIA_HOME would let ~/.asteria/model.routes*.json leak into these assertions.
    monkeypatch.setenv("ASTERIA_HOME", str(Path(os.devnull).parent / "no-such-asteria-home"))


def _validator() -> SchemaValidator:
    return SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")


def _run_dir(tmp_path: Path, overrides: dict | None) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run_config(
        run_dir=run_dir,
        validator=_validator(),
        run_id="run-test-0001",
        mode="goal",
        permission_level="auto",
        model_strategy="auto",
        model_name_overrides=overrides,
    )
    return run_dir


def _configure_zhipu_tier(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    prefix = f"AGENT_MODEL_{tier.upper()}"
    monkeypatch.setenv(f"{prefix}_PROVIDER", "zhipu")
    monkeypatch.setenv(f"{prefix}_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv(f"{prefix}_NAME", "glm-5.1")


def test_pin_replaces_only_the_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _clean_model_env: None
) -> None:
    _configure_zhipu_tier(monkeypatch, "strong")
    client = create_model_client(_run_dir(tmp_path, {"strong": "glm-4.5-air"}), _validator())

    settings = client.client_for_tier("strong").settings
    assert settings.model_name == "glm-4.5-air"
    # The whole safety argument of this feature: credentials and endpoint are untouched.
    assert settings.api_key == "test-key-not-a-real-secret"
    assert settings.provider == "zhipu"
    assert "bigmodel.cn" in settings.base_url


def test_no_pin_keeps_the_env_resolved_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _clean_model_env: None
) -> None:
    # The regression that matters: every existing run has no pin and must behave exactly as before.
    _configure_zhipu_tier(monkeypatch, "strong")
    client = create_model_client(_run_dir(tmp_path, None), _validator())
    assert client.client_for_tier("strong").settings.model_name == "glm-5.1"


def test_pin_applies_to_a_tier_with_no_route_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _clean_model_env: None
) -> None:
    # Single-provider setup: only the global route is configured, so every tier resolves to the
    # default client. A pin here used to land on that shared client — i.e. silently do nothing.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "zhipu")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("AGENT_MODEL_NAME", "glm-5.1")
    client = create_model_client(_run_dir(tmp_path, {"strong": "glm-4.6"}), _validator())

    assert client.client_for_tier("strong").settings.model_name == "glm-4.6"
    # Unpinned tiers keep resolving to the untouched global route.
    assert client.client_for_tier("cheap").settings.model_name == "glm-5.1"


def test_unreadable_run_config_does_not_stop_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _clean_model_env: None
) -> None:
    _configure_zhipu_tier(monkeypatch, "strong")
    run_dir = _run_dir(tmp_path, {"strong": "glm-4.6"})
    (run_dir / "run_config.json").write_text("{ not json", encoding="utf8")
    # No pin is the status quo, and the status quo works — a corrupt file must not decide routing.
    client = create_model_client(run_dir, _validator())
    assert client.client_for_tier("strong").settings.model_name == "glm-5.1"


def test_run_dir_none_is_supported(monkeypatch: pytest.MonkeyPatch, _clean_model_env: None) -> None:
    _configure_zhipu_tier(monkeypatch, "strong")
    client = create_model_client(None, _validator())
    assert client.client_for_tier("strong").settings.model_name == "glm-5.1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"strong": "glm-4.6"}, {"strong": "glm-4.6"}),
        ({"STRONG": "  glm-4.6  "}, {"strong": "glm-4.6"}),  # case/space tolerated
        ({"bogus": "x"}, {}),  # unknown tier dropped, not raised
        ({"strong": ""}, {}),  # blank is "no pin", not a model named ""
        ({"strong": None}, {}),
        ("not a dict", {}),  # hand-edited junk must not raise
        (None, {}),
    ],
)
def test_normalize_drops_junk_instead_of_raising(raw: object, expected: dict) -> None:
    assert normalize_model_name_overrides(raw) == expected
