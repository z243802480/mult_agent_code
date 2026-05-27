from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefaultModelRoute:
    tier: str
    provider: str
    model_name: str
    base_url: str
    deadline_seconds: int
    stream_idle_timeout_seconds: int
    source: str = "default_route_policy"


DEFAULT_MODEL_ROUTES: dict[str, DefaultModelRoute] = {
    "strong": DefaultModelRoute(
        tier="strong",
        provider="glm",
        model_name="glm-5.1",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        deadline_seconds=120,
        stream_idle_timeout_seconds=30,
    ),
    "medium": DefaultModelRoute(
        tier="medium",
        provider="minimax",
        model_name="MiniMax-M2.7",
        base_url="https://api.minimax.io/v1",
        deadline_seconds=90,
        stream_idle_timeout_seconds=30,
    ),
    "cheap": DefaultModelRoute(
        tier="cheap",
        provider="fake",
        model_name="fake-offline",
        base_url="local offline provider",
        deadline_seconds=30,
        stream_idle_timeout_seconds=30,
    ),
}


def default_route_for_tier(tier: str) -> DefaultModelRoute:
    return DEFAULT_MODEL_ROUTES.get(tier, DEFAULT_MODEL_ROUTES["medium"])
