from __future__ import annotations

import json


from pathlib import Path

from asteria_runtime.core.orchestration_spawn_eval import (
    SPAWN_EVAL_TIER,
    SpawnEvalCase,
    build_spawn_eval_messages,
    evaluate_spawn_decision,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class FakeSpawnClient:
    def __init__(self, action: str) -> None:
        self.action = action
        self.last_request: ChatRequest | None = None

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "action": self.action,
                    "reason": "fake",
                    "confidence": "high",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-spawn",
            raw_response={},
        )


def test_spawn_eval_prompt_includes_policy_and_subagent_guidance() -> None:
    messages = build_spawn_eval_messages(
        SpawnEvalCase(
            task_summary="Add logging to greet_cli",
            write_scope=["src/greet_cli.py"],
        )
    )
    blob = "\n".join(message.content for message in messages).lower()
    assert "spawn decision policy" in blob
    assert "when_not_to_use" in blob or "when not" in blob
    assert "keyword" in blob or "file count" in blob


def test_spawn_eval_uses_strong_tier() -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    client = FakeSpawnClient("tool")
    evaluate_spawn_decision(
        SpawnEvalCase(task_summary="Fix typo in README", write_scope=["README.md"]),
        model_client=client,
        validator=validator,
    )
    assert client.last_request is not None
    assert client.last_request.model_tier == SPAWN_EVAL_TIER


def test_spawn_eval_parses_subagent_action() -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    result = evaluate_spawn_decision(
        SpawnEvalCase(
            task_summary="Explore entire repo architecture readonly",
            write_scope=[],
            exploration_breadth="whole_repo",
        ),
        model_client=FakeSpawnClient("subagent"),
        validator=validator,
    )
    assert result.action == "subagent"
    assert result.source == "model"
