from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings, ModelProviderError
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.schema_validator import SchemaValidator


def create_model_client(
    run_dir: Path | None,
    validator: SchemaValidator,
    budget: BudgetController | None = None,
) -> ModelClient:
    provider = os.getenv("AGENT_MODEL_PROVIDER", "minimax").lower()
    if provider != "minimax":
        raise ModelProviderError(f"Unsupported model provider for MVP: {provider}")
    return MiniMaxOpenAICompatibleClient(
        MiniMaxSettings.from_env(),
        logger=ModelCallLogger(run_dir, validator),
        budget=budget,
    )
