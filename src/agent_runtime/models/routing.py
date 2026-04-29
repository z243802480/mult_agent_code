from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.models.base import ChatRequest, ChatResponse, ModelClient


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
        return self.client_for_tier(request.model_tier).chat(request)

    def client_for_tier(self, model_tier: str) -> ModelClient:
        return self.tier_clients.get(model_tier, self.default_client)

    def route_for_tier(self, model_tier: str) -> ModelRoute | None:
        return self.routes.get(model_tier)
