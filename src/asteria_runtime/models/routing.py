from __future__ import annotations

from dataclasses import dataclass, replace

from asteria_runtime.models.base import ChatRequest, ChatResponse, ModelClient


MODEL_TIERS = ("strong", "medium", "cheap")


@dataclass(frozen=True)
class ModelRoute:
    tier: str
    provider: str
    env_prefix: str


class RoutedModelClient:
    def __init__(
        self,
        default_client: ModelClient,
        tier_clients: dict[str, ModelClient],
        routes: dict[str, ModelRoute],
    ) -> None:
        self.default_client = default_client
        self.tier_clients = tier_clients
        self.routes = routes

    def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            return self.client_for_tier(request.model_tier).chat(request)
        except Exception as exc:
            if not self._should_fallback_to_medium(request, exc):
                raise
            fallback_request = replace(
                request,
                model_tier="medium",
                metadata={
                    **dict(request.metadata or {}),
                    "route_fallback": {
                        "from_tier": request.model_tier,
                        "to_tier": "medium",
                        "reason": str(exc),
                        "policy": "strong_timeout_to_medium",
                    },
                },
            )
            response = self.client_for_tier("medium").chat(fallback_request)
            raw_response = dict(response.raw_response or {})
            raw_response["route_fallback"] = {
                "used": True,
                "from_tier": request.model_tier,
                "to_tier": "medium",
                "reason": str(exc),
                "policy": "strong_timeout_to_medium",
            }
            return replace(response, raw_response=raw_response)

    def client_for_tier(self, model_tier: str) -> ModelClient:
        return self.tier_clients.get(model_tier, self.default_client)

    def route_for_tier(self, model_tier: str) -> ModelRoute | None:
        return self.routes.get(model_tier)

    def _should_fallback_to_medium(self, request: ChatRequest, exc: Exception) -> bool:
        if request.model_tier != "strong" or "medium" not in self.tier_clients:
            return False
        metadata = request.metadata or {}
        if metadata.get("disable_route_fallback") is True:
            return False
        text = str(exc).lower()
        return "timeout" in text or "deadline exceeded" in text or "timed out" in text
