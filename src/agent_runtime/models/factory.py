from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.fake import FakeModelClient
from agent_runtime.models.local import local_provider_names, local_settings_from_env
from agent_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings, ModelProviderError
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.models.openai_compatible import OpenAICompatibleClient, OpenAICompatibleSettings
from agent_runtime.models.routing import MODEL_TIERS, ModelRoute, RoutedModelClient
from agent_runtime.storage.schema_validator import SchemaValidator


def create_model_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    budget: BudgetController | None = None,
) -> ModelClient:
    logger = ModelCallLogger(run_dir, validator)
    routes = _routes_from_env()
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
    if provider in {"openai", "openai-compatible", "generic"}:
        return OpenAICompatibleClient(
            OpenAICompatibleSettings.from_env(provider=provider, env_prefix=env_prefix),
            logger=logger,
            budget=budget,
        )
    raise ModelProviderError(f"Unsupported model provider: {provider}")


def _routes_from_env() -> dict[str, ModelRoute]:
    routes = {}
    for tier in MODEL_TIERS:
        env_prefix = f"AGENT_MODEL_{tier.upper()}"
        provider = _provider_from_env(env_prefix)
        if provider:
            routes[tier] = ModelRoute(tier=tier, provider=provider, env_prefix=env_prefix)
    return routes


def _provider_from_env(env_prefix: str, default: str | None = None) -> str:
    provider = os.getenv(f"{env_prefix}_PROVIDER")
    if provider is None and env_prefix == "AGENT_MODEL":
        provider = os.getenv("AGENT_MODEL_PROVIDER")
    return (provider or default or "").lower()
