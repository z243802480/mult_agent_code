from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_router import (
    ORCHESTRATION_ROUTE_TIER,
    resolve_orchestration_route,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class FakeOrchestrationRouterClient:
    last_request: ChatRequest | None = None

    def chat(self, request: ChatRequest) -> ChatResponse:
        FakeOrchestrationRouterClient.last_request = request
        return ChatResponse(
            content=(
                '{"schema_version":"0.1.0","capability_id":"chat_answer",'
                '"reason":"Question without file changes.","confidence":"high"}'
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-router",
            raw_response={},
        )


def test_model_mode_uses_strong_tier_for_routing(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    client = FakeOrchestrationRouterClient()

    routed = resolve_orchestration_route(
        tmp_path,
        "Python 里 list 和 tuple 有什么区别？",
        validator=validator,
        model_client=client,
        router_mode="model",
    )
    assert routed.capability_id == "chat_answer"
    assert routed.source == "model"
    assert FakeOrchestrationRouterClient.last_request is not None
    assert FakeOrchestrationRouterClient.last_request.model_tier == ORCHESTRATION_ROUTE_TIER


def test_conservative_fallback_when_model_unavailable(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)

    routed = resolve_orchestration_route(
        tmp_path,
        "任意消息",
        validator=validator,
        model_client=None,
        model_client_factory=None,
        router_mode="model",
    )
    assert routed.capability_id == "chat_answer"
    assert routed.source == "conservative_fallback"
