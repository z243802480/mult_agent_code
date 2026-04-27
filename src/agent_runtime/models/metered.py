from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.core.budget import BudgetController, BudgetExceededError
from agent_runtime.models.base import ChatRequest, ChatResponse, ModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger


@dataclass
class MeteredModelClient:
    delegate: ModelClient
    budget: BudgetController
    logger: ModelCallLogger
    provider: str = "metered"
    model_name: str = "external"

    def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            self.budget.record_model_call(request.model_tier)
        except BudgetExceededError as exc:
            self.logger.record_failure(
                request,
                provider=self.provider,
                model_name=self.model_name,
                model_tier=request.model_tier,
                error=str(exc),
            )
            raise

        try:
            response = self.delegate.chat(request)
        except Exception as exc:
            self.logger.record_failure(
                request,
                provider=self.provider,
                model_name=self.model_name,
                model_tier=request.model_tier,
                error=str(exc),
            )
            raise

        self.budget.record_model_tokens(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        self.logger.record_success(request, response)
        return response
