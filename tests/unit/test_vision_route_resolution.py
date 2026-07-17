from __future__ import annotations

import pytest

from asteria_runtime.models import factory
from asteria_runtime.models.factory import VISION_ENV_PREFIX, vision_route_configured


def _local_config(values: dict[str, str]):
    """Stand in for the on-disk route config, INCLUDING its global-inheritance fallback.

    The inheritance that caused the bug lives in ``local_route_config.local_route_value`` (file
    lookup), not in os.environ — testing via env vars would pass against the buggy code too.
    """

    def _local_route_value(prefix: str, key: str) -> str:
        exact = values.get(f"{prefix}_{key}")
        if exact:
            return exact
        if prefix != "AGENT_MODEL":  # local_route_config.py:47-48
            return values.get(f"AGENT_MODEL_{key}", "")
        return ""

    def _any_local_route_value(names: tuple[str, ...]) -> str:
        for name in names:
            if values.get(name):
                return values[name]
        return ""

    return _local_route_value, _any_local_route_value


@pytest.fixture(autouse=True)
def _isolated_route_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from the developer's real ~/.asteria route config (empty by default)."""
    monkeypatch.delenv(f"{VISION_ENV_PREFIX}_PROVIDER", raising=False)
    monkeypatch.delenv(f"{VISION_ENV_PREFIX}_NAME", raising=False)
    local, anyv = _local_config({})
    monkeypatch.setattr(factory, "local_route_value", local)
    monkeypatch.setattr(factory, "any_local_route_value", anyv)


def test_unconfigured_vision_route_is_not_inherited_from_the_global_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this test exists for: a capability probe must not ride the tier fallback.

    ``local_route_value`` falls back to ``AGENT_MODEL_PROVIDER`` for any non-global prefix. That is
    correct for tiers — a tier with no provider of its own should ride the global route — but for
    vision it reported "configured" for users who had never set up a vision model, which bypassed
    the honest refusal and sent the image to the text-only route that answers HTTP 400 code 1210.

    Verified to fail against the pre-fix implementation: with this exact config,
    ``_provider_from_env("AGENT_MODEL_VISION")`` returned ``"zai"``.
    """
    local, anyv = _local_config({"AGENT_MODEL_PROVIDER": "zai", "AGENT_MODEL_NAME": "glm-5"})
    monkeypatch.setattr(factory, "local_route_value", local)
    monkeypatch.setattr(factory, "any_local_route_value", anyv)

    # Guard the premise: the tier helper DOES inherit here — that is the trap being avoided.
    assert factory._provider_from_env(VISION_ENV_PREFIX) == "zai"
    assert vision_route_configured() is False
    assert factory.create_vision_client(None, _validator()) is None


def test_vision_route_in_local_config_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    local, anyv = _local_config(
        {
            "AGENT_MODEL_PROVIDER": "zai",
            f"{VISION_ENV_PREFIX}_PROVIDER": "zhipu",
            f"{VISION_ENV_PREFIX}_NAME": "glm-4.5v",
        }
    )
    monkeypatch.setattr(factory, "local_route_value", local)
    monkeypatch.setattr(factory, "any_local_route_value", anyv)

    assert vision_route_configured() is True


def test_blank_vision_name_counts_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_PROVIDER", "zhipu")
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_NAME", "   ")
    assert vision_route_configured() is False


def test_blank_vision_provider_counts_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_PROVIDER", "   ")
    assert vision_route_configured() is False


def test_probe_and_builder_agree_on_whether_a_route_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # They share _vision_provider precisely so they can never disagree: a True probe followed by a
    # None build (or vice versa) is what produced the bypass in the first place.
    local, anyv = _local_config({"AGENT_MODEL_PROVIDER": "zai"})
    monkeypatch.setattr(factory, "local_route_value", local)
    monkeypatch.setattr(factory, "any_local_route_value", anyv)

    assert vision_route_configured() is (
        factory.create_vision_client(None, _validator()) is not None
    )


def test_local_route_lookup_uses_the_exact_vision_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The local-config path must be queried by exact name, not the inheriting helper."""
    seen: list[tuple[str, ...]] = []

    def _spy(names: tuple[str, ...]) -> str:
        seen.append(names)
        return ""

    monkeypatch.setattr(factory, "any_local_route_value", _spy)
    vision_route_configured()

    # Exact vision names only — never the inheriting AGENT_MODEL_* fallback.
    assert seen == [(f"{VISION_ENV_PREFIX}_PROVIDER",)]


def _validator() -> object:
    from pathlib import Path

    from asteria_runtime.storage.schema_validator import SchemaValidator

    return SchemaValidator(Path("schemas"))


def test_provider_alone_is_not_a_vision_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """The half-fix this test exists for.

    Forcing only PROVIDER to be explicit left NAME inheriting the global text model, so the probe
    said "vision is configured" about a route pointing at glm-5 on the coding endpoint — the same
    HTTP 400/1210 failure the explicit-provider rule was added to prevent, moved one field over.
    """
    local, anyv = _local_config({"AGENT_MODEL_NAME": "glm-5", "AGENT_MODEL_PROVIDER": "zai"})
    monkeypatch.setattr(factory, "local_route_value", local)
    monkeypatch.setattr(factory, "any_local_route_value", anyv)
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_PROVIDER", "zhipu")

    assert vision_route_configured() is False
    assert factory.create_vision_client(None, _validator()) is None


def test_provider_and_name_together_are_a_vision_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_PROVIDER", "zhipu")
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_NAME", "glm-4.5v")
    assert vision_route_configured() is True


def test_name_alone_is_not_a_vision_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{VISION_ENV_PREFIX}_NAME", "glm-4.5v")
    assert vision_route_configured() is False
