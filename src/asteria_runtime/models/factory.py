from __future__ import annotations

import os
import warnings
from pathlib import Path

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.local_route_config import configured_route_tiers, local_route_value
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
    _warn_if_tier_silently_offline(routes)
    default_route = _default_route(routes)
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


def _warn_if_tier_silently_offline(routes: dict[str, ModelRoute]) -> list[str]:
    """Warn when a tier resolves to the fake/offline provider while real providers are configured.

    The default route policy points `cheap` at the fake/offline provider, and docs show
    `AGENT_MODEL_CHEAP_PROVIDER=fake` as an offline default. A fully-offline run is intentional and
    stays quiet; but when an offline tier is *mixed* with real providers, any call routed to it
    (summaries, classification, some model-checks) silently returns canned output. Surface that once
    so the canned output is never silent (D-3 decision: keep the fake default, but warn).
    """
    offline = {"fake", "offline"}
    offline_tiers = sorted(tier for tier, route in routes.items() if route.provider in offline)
    real_tiers = sorted(tier for tier, route in routes.items() if route.provider not in offline)
    if offline_tiers and real_tiers:
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
