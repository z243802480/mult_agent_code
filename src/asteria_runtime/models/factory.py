from __future__ import annotations

import os
import warnings
from dataclasses import replace
from pathlib import Path

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.local_route_config import (
    any_local_route_value,
    configured_route_tiers,
    local_route_value,
)
from asteria_runtime.models.local import local_provider_names, local_settings_from_env
from asteria_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings, ModelProviderError
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.models.openai_compatible import OpenAICompatibleClient, OpenAICompatibleSettings
from asteria_runtime.models.routing import MODEL_TIERS, ModelRoute, RoutedModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator

ZHIPU_PROVIDER_ALIASES = {"zhipu", "bigmodel"}
ZAI_PROVIDER_ALIASES = {"zai", "z-ai", "glm"}


def create_model_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    budget: BudgetController | None = None,
) -> ModelClient:
    logger = ModelCallLogger(run_dir, validator)
    routes = _routes_from_env()
    default_route = _default_route(routes)
    _warn_if_tier_silently_offline(routes, default_route)
    # Which model backs a tier is resolved from env / the local route file; this run may pin a
    # different model name per tier (G8-b). Read from the run's OWN run_config.json rather than a
    # constructor argument, so resume/continue keep the pin the same way they keep the permission
    # tier — the file is on disk, the CLI default is not consulted again. Written before this call
    # (plan_command writes run_config, then builds the client).
    overrides = _model_name_overrides(run_dir, validator)
    default_client = _create_provider_client(
        default_route.provider,
        default_route.env_prefix,
        logger,
        budget,
        overrides.get(default_route.tier),
    )
    tier_clients = {
        tier: _create_provider_client(
            route.provider, route.env_prefix, logger, budget, overrides.get(tier)
        )
        for tier, route in routes.items()
    }
    # A tier can be pinned without having a provider route of its own: the common single-provider
    # setup configures AGENT_MODEL_PROVIDER only, every tier resolves to `default_client`, and a pin
    # would land on a client shared with the other tiers — i.e. silently do nothing. Mint that tier
    # its own client instead, on the default route's provider and credentials, differing only in the
    # model asked for. Side effect worth knowing: strong->medium timeout fallback keys off the two
    # tiers resolving to *different* clients, so pinning one of them enables a fallback that a
    # single-provider setup did not have. That is the honest reading — they are now different models.
    for tier, model_name in overrides.items():
        if tier in tier_clients:
            continue
        tier_clients[tier] = _create_provider_client(
            default_route.provider, default_route.env_prefix, logger, budget, model_name
        )
        routes[tier] = ModelRoute(
            tier=tier, provider=default_route.provider, env_prefix=default_route.env_prefix
        )
    if not tier_clients:
        return default_client
    return RoutedModelClient(default_client, tier_clients, routes)


def _model_name_overrides(run_dir: Path | None, validator: SchemaValidator) -> dict:
    # Never let a bad/absent run_config stop a run from starting: no pin is the status quo, and the
    # status quo works. Re-normalized (not trusted as read) because the file is hand-editable.
    if run_dir is None:
        return {}
    try:
        from asteria_runtime.core.run_config import load_run_config, normalize_model_name_overrides

        config = load_run_config(run_dir, validator)
    except Exception:  # noqa: BLE001 - an unreadable config must not decide model routing
        return {}
    return normalize_model_name_overrides((config or {}).get("model_name_overrides"))


def real_route_for_tier(tier: str = "medium") -> ModelRoute | None:
    """Resolved route for ``tier`` IF it uses a real provider, else ``None``.

    Mirrors the offline set used by :func:`_warn_if_tier_silently_offline`. Lets best-effort
    features (e.g. the closing recap) decide "is a real model reachable for this tier?" so an
    air-gapped / fake-only run keeps its structured fallback instead of surfacing canned text.
    """
    routes = _routes_from_env()
    route = routes.get(tier) or _default_route(routes)
    if route is None or route.provider in {"fake", "offline"}:
        return None
    return route


def create_recap_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    tier: str = "medium",
) -> ModelClient | None:
    """Best-effort routed client for a conversational closing recap, or ``None`` when offline.

    The CLI/Studio path builds RunCommand without injecting model clients (execution creates its
    own run-scoped client internally), so the recap would otherwise never run and every real run
    falls back to the robotic status-line conclusion. This mints a client for the recap WITHOUT
    perturbing the execution path — but returns ``None`` on a fake/offline tier so an air-gapped
    run keeps its clean structured conclusion rather than a canned fake recap. Never raises.
    """
    if real_route_for_tier(tier) is None:
        return None
    try:
        return create_model_client(run_dir, validator)
    except Exception:  # noqa: BLE001 — recap is best-effort; never fail the run.
        return None


VISION_ENV_PREFIX = "AGENT_MODEL_VISION"


def _explicit_vision_value(key: str) -> str:
    """A vision field read from the vision route ONLY — never inherited from the global route.

    Deliberately avoids :func:`_provider_from_env` / ``local_route_value``, which fall back to
    ``AGENT_MODEL_<KEY>`` when a per-prefix value is missing. That inheritance is right for tiers —
    a tier with no provider of its own genuinely should ride the global route — and wrong here: a
    user who never configured vision would be reported as having a vision route, the honest refusal
    would never fire, and the image would go to the global text route, which is precisely the
    endpoint that answers HTTP 400 code 1210.
    """
    value = os.getenv(f"{VISION_ENV_PREFIX}_{key}") or any_local_route_value(
        (f"{VISION_ENV_PREFIX}_{key}",)
    )
    return value.strip()


def _vision_provider() -> str:
    return _explicit_vision_value("PROVIDER").lower()


def vision_route_configured() -> bool:
    """Whether a vision route exists, without building a client (no run_dir, no side effects).

    Requires BOTH provider and model name to be set on the vision route. Provider alone does not
    make a route a vision route: with only ``AGENT_MODEL_VISION_PROVIDER`` set, the model name
    still inherits the global ``AGENT_MODEL_NAME`` (a text model), so the probe would say "vision
    is configured" about a route pointing at a text model — the same failure as the inheritance
    this function exists to block, just moved one field over.

    BASE_URL can still inherit, which is a narrower hole with a loud failure: the request reaches a
    text endpoint and returns HTTP 400, which callers surface with the four variables to set. See
    the brief's known-boundaries section.

    Shares its reads with :func:`create_vision_client`, so the probe and the build can never
    disagree about whether a route exists.
    """
    return bool(_vision_provider() and _explicit_vision_value("NAME"))


def create_vision_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    budget: BudgetController | None = None,
) -> ModelClient | None:
    """Client for the vision route, or ``None`` when no vision route is configured.

    Deliberately NOT a member of ``MODEL_TIERS``: tiers are a cost axis (strong/medium/cheap) that
    drives ``model_strategy`` preference and the strong→medium timeout fallback, so folding a
    capability into it would corrupt both. This mirrors :func:`create_recap_client` — a
    purpose-specific client resolved outside the tier system.

    Returning ``None`` rather than falling back matters: a real probe (2026-07-17) showed the
    configured strong route (glm-5 on the coding endpoint) rejects images outright with
    ``HTTP 400 code 1210: messages.content.type ... ['text']``. Silently routing an image to a
    text-only model would either hard-fail mid-run or, worse, drop the image and let the model
    answer as if it had seen one. Callers must degrade honestly instead.
    """
    if not vision_route_configured():
        return None
    logger = ModelCallLogger(run_dir, validator)
    return _create_provider_client(_vision_provider(), VISION_ENV_PREFIX, logger, budget)


def _warn_if_tier_silently_offline(
    routes: dict[str, ModelRoute],
    default_route: ModelRoute | None = None,
) -> list[str]:
    """Warn when a tier resolves to the fake/offline provider while real providers are configured.

    The default route policy points `cheap` at the fake/offline provider, and docs show
    `AGENT_MODEL_CHEAP_PROVIDER=fake` as an offline default. A fully-offline run is intentional and
    stays quiet; but when an offline tier is *mixed* with real providers, any call routed to it
    (summaries, classification, some model-checks) silently returns canned output. Surface that once
    so the canned output is never silent (D-3 decision: keep the fake default, but warn).

    The real provider often lives on the GLOBAL/default route (`AGENT_MODEL_PROVIDER`), not in the
    per-tier `routes` dict — e.g. `AGENT_MODEL_PROVIDER=minimax` + only `AGENT_MODEL_CHEAP_PROVIDER=
    fake`. Counting real providers from `routes` alone missed that case (false negative), so a mixed
    config produced silent canned `cheap` output with no warning. Fold the default route in.
    """
    offline = {"fake", "offline"}
    offline_tiers = sorted(tier for tier, route in routes.items() if route.provider in offline)
    real_tiers = sorted(tier for tier, route in routes.items() if route.provider not in offline)
    default_is_real = (
        default_route is not None
        and bool(default_route.provider)
        and default_route.provider not in offline
    )
    if offline_tiers and (real_tiers or default_is_real):
        warnings.warn(
            f"model tier(s) {offline_tiers} use the fake/offline provider while real providers are "
            f"configured for {real_tiers}; calls routed to {offline_tiers} return canned output. "
            "Set the corresponding AGENT_MODEL_<TIER>_PROVIDER to a real provider to avoid silent "
            "canned output.",
            stacklevel=3,
        )
    return offline_tiers


def _default_route(routes: dict[str, ModelRoute]) -> ModelRoute:
    global_provider = _provider_from_env("AGENT_MODEL")
    if global_provider:
        return ModelRoute(tier="default", provider=global_provider, env_prefix="AGENT_MODEL")
    if "medium" in routes:
        return routes["medium"]
    if routes:
        return next(iter(routes.values()))
    return ModelRoute(tier="default", provider="minimax", env_prefix="AGENT_MODEL")


def _create_provider_client(
    provider: str,
    env_prefix: str,
    logger: ModelCallLogger,
    budget: BudgetController | None,
    model_name: str | None = None,
) -> ModelClient:
    if provider in {"fake", "offline"}:
        # No pin: a fake/offline client fabricates output and has no model to talk to.
        return FakeModelClient(logger=logger, budget=budget)
    if provider in local_provider_names():
        return OpenAICompatibleClient(
            _pinned(local_settings_from_env(provider, env_prefix=env_prefix), model_name),
            logger=logger,
            budget=budget,
        )
    if provider == "minimax":
        return MiniMaxOpenAICompatibleClient(
            _pinned(MiniMaxSettings.from_env(env_prefix=env_prefix), model_name),
            logger=logger,
            budget=budget,
        )
    if provider in ZHIPU_PROVIDER_ALIASES:
        return OpenAICompatibleClient(
            _pinned(
                OpenAICompatibleSettings.from_env(
                    provider="zhipu",
                    env_prefix=env_prefix,
                    default_base_url="https://open.bigmodel.cn/api/paas/v4",
                    default_model_name="glm-5.1",
                    api_key_env_names=("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY"),
                ),
                model_name,
            ),
            logger=logger,
            budget=budget,
        )
    if provider in ZAI_PROVIDER_ALIASES:
        return OpenAICompatibleClient(
            _pinned(
                OpenAICompatibleSettings.from_env(
                    provider="zai",
                    env_prefix=env_prefix,
                    default_base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                    default_model_name="glm-5.1",
                    api_key_env_names=("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
                ),
                model_name,
            ),
            logger=logger,
            budget=budget,
        )
    if provider in {"openai", "openai-compatible", "generic"}:
        return OpenAICompatibleClient(
            _pinned(
                OpenAICompatibleSettings.from_env(provider=provider, env_prefix=env_prefix),
                model_name,
            ),
            logger=logger,
            budget=budget,
        )
    raise ModelProviderError(f"Unsupported model provider: {provider}")


def _pinned(settings, model_name: str | None):
    """`settings` with `model_name` swapped for the run's pin, keeping every other field.

    Applied here, on the settings each provider already resolved from env, rather than by teaching
    each `from_env` an override parameter: every settings class is a frozen dataclass carrying a
    `model_name`, so one `replace` covers all providers, and the provider modules stay untouched.
    Credentials, base_url and timeouts keep coming from that tier's configured route — a pin says
    which model to ask for, never who to ask or with whose key.
    """
    if not model_name:
        return settings
    return replace(settings, model_name=model_name)


def _routes_from_env() -> dict[str, ModelRoute]:
    routes = {}
    for tier in sorted(set(MODEL_TIERS) | configured_route_tiers()):
        env_prefix = f"AGENT_MODEL_{tier.upper()}"
        provider = _provider_from_env(env_prefix)
        if provider:
            routes[tier] = ModelRoute(tier=tier, provider=provider, env_prefix=env_prefix)
    return routes


def _provider_from_env(env_prefix: str, default: str | None = None) -> str:
    provider = os.getenv(f"{env_prefix}_PROVIDER")
    if provider is None:
        provider = local_route_value(env_prefix, "PROVIDER")
    if provider is None and env_prefix == "AGENT_MODEL":
        provider = os.getenv("AGENT_MODEL_PROVIDER")
    if not provider and env_prefix == "AGENT_MODEL":
        provider = local_route_value("AGENT_MODEL", "PROVIDER")
    return (provider or default or "").lower()
