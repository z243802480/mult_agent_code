"""D-3: the fake/offline default route must not silently produce canned output.

The default route policy points `cheap` at the fake/offline provider. When that is mixed with real
providers in a real run, calls routed to the offline tier silently return canned output. The factory
keeps the fake default (offline runs are intentional) but emits a runtime warning when an offline
tier is mixed with real ones.
"""

import warnings

import pytest

from asteria_runtime.models.factory import _warn_if_tier_silently_offline
from asteria_runtime.models.routing import ModelRoute


def _route(tier: str, provider: str) -> ModelRoute:
    return ModelRoute(tier=tier, provider=provider, env_prefix=f"AGENT_MODEL_{tier.upper()}")


def test_warns_when_offline_tier_mixed_with_real_providers() -> None:
    routes = {
        "strong": _route("strong", "zai"),
        "medium": _route("medium", "minimax"),
        "cheap": _route("cheap", "fake"),
    }
    with pytest.warns(UserWarning, match="canned output"):
        offline = _warn_if_tier_silently_offline(routes)
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
