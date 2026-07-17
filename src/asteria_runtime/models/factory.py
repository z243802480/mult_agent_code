from __future__ import annotations

import os
import warnings
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
    default_client = _create_provider_client(
        default_route.provider,
        default_route.env_prefix,
        logger,
        budget,
    )
    if not routes:
        return default_client
    tier_clients = {
        tier: _create_provider_client(route.provider, route.env_prefix, logger, budget)
        for tier, route in routes.items()
    }
    return RoutedModelClient(default_client, tier_clients, routes)


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


def _vision_provider() -> str:
    """The EXPLICITLY configured vision provider, or "" — never inherited from the global route.

    Deliberately does not use :func:`_provider_from_env`. That helper (via ``local_route_value``)
    falls back to ``AGENT_MODEL_PROVIDER`` when a per-prefix value is missing, which is right for
    tiers — a tier with no provider of its own genuinely should ride the global route — but wrong
    for a capability probe. Inheriting there means a user who never configured vision is reported
    as having a vision route, the honest refusal never fires, and the image is sent to the global
    text route, which is exactly the endpoint that answers HTTP 400 code 1210. "Not configured"
    must mean not configured.
    """
    provider = os.getenv(f"{VISION_ENV_PREFIX}_PROVIDER") or any_local_route_value(
        (f"{VISION_ENV_PREFIX}_PROVIDER",)
    )
    return provider.strip().lower()


def vision_route_configured() -> bool:
    """Whether a vision route exists, without building a client (no run_dir, no side effects).

    Lets callers refuse an image question up front instead of doing context work first. Shares
    :func:`_vision_provider` with :func:`create_vision_client` so the probe and the build can never
    disagree about whether a route exists.
    """
    return bool(_vision_provider())


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
    provider = _vision_provider()
    if not provider:
        return None
    logger = ModelCallLogger(run_dir, validator)
    return _create_provider_client(provider, VISION_ENV_PREFIX, logger, budget)


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
) -> ModelClient:
    if provider in {"fake", "offline"}:
        return FakeModelClient(logger=logger, budget=budget)
    if provider in local_provider_names():
        return OpenAICompatibleClient(
            local_settings_from_env(provider, env_prefix=env_prefix),
            logger=logger,
            budget=budget,
        )
    if provider == "minimax":
        return MiniMaxOpenAICompatibleClient(
            MiniMaxSettings.from_env(env_prefix=env_prefix),
            logger=logger,
            budget=budget,
        )
    if provider in ZHIPU_PROVIDER_ALIASES:
        return OpenAICompatibleClient(
            OpenAICompatibleSettings.from_env(
                provider="zhipu",
                env_prefix=env_prefix,
                default_base_url="https://open.bigmodel.cn/api/paas/v4",
                default_model_name="glm-5.1",
                api_key_env_names=("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY"),
            ),
            logger=logger,
            budget=budget,
        )
    if provider in ZAI_PROVIDER_ALIASES:
        return OpenAICompatibleClient(
            OpenAICompatibleSettings.from_env(
                provider="zai",
                env_prefix=env_prefix,
                default_base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                default_model_name="glm-5.1",
                api_key_env_names=("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
            ),
            logger=logger,
            budget=budget,
        )
    if provider in {"openai", "openai-compatible", "generic"}:
        return OpenAICompatibleClient(
            OpenAICompatibleSettings.from_env(provider=provider, env_prefix=env_prefix),
            logger=logger,
            budget=budget,
        )
    raise ModelProviderError(f"Unsupported model provider: {provider}")


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
