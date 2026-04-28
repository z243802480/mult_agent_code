from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.fake import FakeModelClient
from agent_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings, ModelProviderError
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.models.openai_compatible import OpenAICompatibleClient, OpenAICompatibleSettings
from agent_runtime.storage.schema_validator import SchemaValidator


def create_model_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    budget: BudgetController | None = None,
) -> ModelClient:
    provider = os.getenv("AGENT_MODEL_PROVIDER", "minimax").lower()
    logger = ModelCallLogger(run_dir, validator)
    if provider in {"fake", "offline"}:
        return FakeModelClient(logger=logger)
    if provider == "minimax":
        return MiniMaxOpenAICompatibleClient(
            MiniMaxSettings.from_env(),
            logger=logger,
            budget=budget,
        )
    if provider in {"openai", "openai-compatible", "generic"}:
        return OpenAICompatibleClient(
            OpenAICompatibleSettings.from_env(provider=provider),
            logger=logger,
            budget=budget,
        )
    raise ModelProviderError(f"Unsupported model provider: {provider}")
