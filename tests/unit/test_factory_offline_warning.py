"""D-3: the fake/offline default route must not silently produce canned output.

The default route policy points `cheap` at the fake/offline provider. When that is mixed with real
providers in a real run, calls routed to the offline tier silently return canned output. The factory
keeps the fake default (offline runs are intentional) but emits a runtime warning when an offline
tier is mixed with real ones.
"""

import warnings

import pytest

from asteria_runtime.models.factory import _warn_if_tier_silently_offline
from asteria_runtime.models.route_diagnostics import silently_canned_tiers
from asteria_runtime.models.routing import ModelRoute


def _route(tier: str, provider: str) -> ModelRoute:
    return ModelRoute(tier=tier, provider=provider, env_prefix=f"AGENT_MODEL_{tier.upper()}")


@pytest.fixture()
def _clean_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every ambient AGENT_MODEL_*/provider-key env so route resolution is deterministic."""
    import os

    for key in list(os.environ):
        if key.startswith("AGENT_MODEL") or key in {
            "MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "ZAI_API_KEY", "GLM_API_KEY",
            "ZHIPU_API_KEY", "BIGMODEL_API_KEY", "OPENAI_API_KEY",
        }:
            monkeypatch.delenv(key, raising=False)


def test_warns_when_offline_tier_mixed_with_real_providers() -> None:
    routes = {
        "strong": _route("strong", "zai"),
        "medium": _route("medium", "minimax"),
        "cheap": _route("cheap", "fake"),
    }
    with pytest.warns(UserWarning, match="canned output"):
        offline = _warn_if_tier_silently_offline(routes)
    assert offline == ["cheap"]


def test_warns_when_only_offline_tier_and_real_default_route() -> None:
    # False-negative regression: the real provider lives on the GLOBAL/default route
    # (AGENT_MODEL_PROVIDER=minimax) while only `cheap` is pinned to fake. `routes` alone has no
    # real tier, so the old predicate stayed silent even though `cheap` calls return canned output.
    routes = {"cheap": _route("cheap", "fake")}
    default_route = ModelRoute(tier="default", provider="minimax", env_prefix="AGENT_MODEL")
    with pytest.warns(UserWarning, match="canned output"):
        offline = _warn_if_tier_silently_offline(routes, default_route)
    assert offline == ["cheap"]


def test_quiet_when_only_offline_tier_and_offline_default_route() -> None:
    # Fully offline (default route also fake) stays quiet even with the default-route check.
    routes = {"cheap": _route("cheap", "fake")}
    default_route = ModelRoute(tier="default", provider="fake", env_prefix="AGENT_MODEL")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        offline = _warn_if_tier_silently_offline(routes, default_route)
    assert offline == ["cheap"]


def test_quiet_when_every_tier_is_offline() -> None:
    # A fully offline/test run is intentional — no warning.
    routes = {
        "strong": _route("strong", "fake"),
        "medium": _route("medium", "offline"),
        "cheap": _route("cheap", "fake"),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any emitted warning would raise here
        offline = _warn_if_tier_silently_offline(routes)
    assert offline == ["cheap", "medium", "strong"]


def test_quiet_when_every_tier_is_real() -> None:
    routes = {
        "strong": _route("strong", "zai"),
        "medium": _route("medium", "minimax"),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        offline = _warn_if_tier_silently_offline(routes)
    assert offline == []


# silently_canned_tiers is the honest source the CLI run-path banner reads to surface the
# mixed-canned footgun loudly (Python warnings.warn is easily filtered/lost mid-run).


def test_silently_canned_tiers_flags_mixed_config(_clean_model_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "x")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "x")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")
    assert silently_canned_tiers() == ["cheap"]


def test_silently_canned_tiers_flags_mixed_via_global_default(_clean_model_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # The real provider lives on the GLOBAL default route while only `cheap` is pinned to fake —
    # the false-negative case the factory warning was specifically extended to catch.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "x")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")
    assert silently_canned_tiers() == ["cheap"]


def test_silently_canned_tiers_quiet_when_fully_offline(_clean_model_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for tier in ("STRONG", "MEDIUM", "CHEAP"):
        monkeypatch.setenv(f"AGENT_MODEL_{tier}_PROVIDER", "fake")
    assert silently_canned_tiers() == []


def test_silently_canned_tiers_quiet_when_fully_real(_clean_model_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for tier in ("STRONG", "MEDIUM", "CHEAP"):
        monkeypatch.setenv(f"AGENT_MODEL_{tier}_PROVIDER", "minimax")
        monkeypatch.setenv(f"AGENT_MODEL_{tier}_API_KEY", "x")
    assert silently_canned_tiers() == []
