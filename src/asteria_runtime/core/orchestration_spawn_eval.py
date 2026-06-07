"""Spawn decision evaluation (S63-3) — strong model reads policy + task context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.orchestration_spawn_policy import (
    SPAWN_DECISION_POLICY,
    subagent_capability_description,
    subagent_manifest_extras,
)
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidator

SPAWN_EVAL_TIER = "strong"
ALLOWED_SPAWN_ACTIONS = frozenset({"tool", "subagent"})


class SpawnEvalError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpawnEvalCase:
    task_summary: str
    write_scope: list[str]
    exploration_breadth: str = "single_file"
    task_id: str = "task-1"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SpawnEvalCase:
        return cls(
            task_summary=str(payload.get("task_summary") or "").strip(),
            write_scope=[str(item) for item in (payload.get("write_scope") or [])],
            exploration_breadth=str(payload.get("exploration_breadth") or "single_file"),
            task_id=str(payload.get("task_id") or "task-1"),
        )


@dataclass(frozen=True)
class SpawnEvalResult:
    action: str
    reason: str
    confidence: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "source": self.source,
        }


def build_spawn_eval_messages(case: SpawnEvalCase) -> list[ChatMessage]:
    extras = subagent_manifest_extras()
    system_prompt = (
        "You are Asteria's AgentLoop spawn advisor (Claude Code-aligned). "
        "Read the spawn decision policy, subagent capability description, and task context. "
        "Choose whether the next AgentLoopDecision should use direct tools (`tool`) or "
        "delegate via `subagent`. "
        "Prefer `tool` for small scoped edits completable in one loop. "
        "Choose `subagent` only when strong judgment says context isolation, parallel readonly "
        "exploration, or independent verification is required. "
        "Never decide from keyword lists, file counts, or task counts. "
        "Return only JSON."
    )
    user_prompt = "\n\n".join(
        [
            "Spawn decision policy:",
            json.dumps(SPAWN_DECISION_POLICY.to_dict(), ensure_ascii=False, indent=2),
            "Subagent capability:",
            subagent_capability_description(),
            "Subagent when_to_use:",
            json.dumps(extras["when_to_use"], ensure_ascii=False, indent=2),
            "Subagent when_not_to_use:",
            json.dumps(extras["when_not_to_use"], ensure_ascii=False, indent=2),
            "Task context:",
            json.dumps(
                {
                    "task_id": case.task_id,
                    "task_summary": case.task_summary,
                    "write_scope": case.write_scope,
                    "exploration_breadth": case.exploration_breadth,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "Return JSON:",
            '{"schema_version":"0.1.0","action":"tool|subagent","reason":"...","confidence":"high|medium|low"}',
        ]
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]


def evaluate_spawn_decision(
    case: SpawnEvalCase,
    *,
    model_client: ModelClient,
    validator: SchemaValidator,
) -> SpawnEvalResult:
    messages = build_spawn_eval_messages(case)
    response = model_client.chat(
        ChatRequest(
            purpose="spawn_decision_eval",
            model_tier=SPAWN_EVAL_TIER,
            messages=messages,
            temperature=0.0,
            metadata={"purpose": "spawn_decision_eval", "model_tier": SPAWN_EVAL_TIER},
        )
    )
    try:
        parsed = parse_json_object(response.content)
    except JsonExtractionError as exc:
        raise SpawnEvalError(f"Spawn eval returned invalid JSON: {exc}") from exc
    validator.validate("spawn_eval_choice", parsed)
    action = str(parsed.get("action") or "").strip().lower()
    if action not in ALLOWED_SPAWN_ACTIONS:
        raise SpawnEvalError(f"Unsupported spawn action: {action}")
    return SpawnEvalResult(
        action=action,
        reason=str(parsed.get("reason") or ""),
        confidence=str(parsed.get("confidence") or "medium"),
        source="model",
    )
