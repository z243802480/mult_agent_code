from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.budget import BudgetController, BudgetExceededError
from asteria_runtime.core.context_budget import estimate_request_context
from asteria_runtime.models.base import ChatRequest, ChatResponse, ModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger


@dataclass
class MeteredModelClient:
    delegate: ModelClient
    budget: BudgetController
    logger: ModelCallLogger
    provider: str = "metered"
    model_name: str = "external"

    def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            estimate = estimate_request_context(request)
            self.budget.record_context_estimate(
                estimate.total_tokens,
                sections=estimate.sections,
                duplicate_content_hashes=estimate.duplicate_content_hashes,
                model_name=self.model_name,
                provider=self.provider,
            )
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
        # Truth feedback (S90): the provider-reported prompt size for THIS request replaces the
        # char-heuristic guess as the pressure signal of record and calibrates future estimates.
        self.budget.record_context_observation(
            response.usage.input_tokens,
            model_name=self.model_name,
            provider=self.provider,
        )
        self.logger.record_success(request, response)
        return response
