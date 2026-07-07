"""Spine-aware fake helpers (RA7b slice 3).

Translate a legacy execute fake's tool intent into the 立真身 model-driven turn contract
``{narration, tool_calls, done}`` so orchestration tests (run/review/replan/...) drive the spine
(the production default) instead of the FSM ``ExecutionAction`` path being retired.

Turn detection is stateless: the spine always sets ``request.metadata['iteration']`` — iteration 1
runs the tools, iteration >= 2 finishes (``done=true``). One work turn + one close turn is exactly
what a happy-path task needs; the correctness gate (task_contract) still classifies done vs blocked
from the observations the tools actually produced.
"""

from __future__ import annotations

import json
from typing import Any

from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


def is_spine_request(request: ChatRequest) -> bool:
    """True when the request is a 立真身 turn (vs a plan/review/FSM-execute request)."""
    return (getattr(request, "metadata", None) or {}).get("loop") == "model_driven_turn"


def spine_turn(request: ChatRequest) -> int:
    return int((getattr(request, "metadata", None) or {}).get("iteration") or 1)


def spine_response(
    request: ChatRequest,
    *,
    tool_calls: list[dict[str, Any]],
    narration: str = "执行并验证任务。",
    final: str = "任务已完成并验证。",
    model_name: str = "fake-spine",
) -> ChatResponse:
    """Build a model-driven-turn ChatResponse: run ``tool_calls`` on turn 1, finish afterwards."""
    if spine_turn(request) <= 1:
        payload = {"narration": narration, "tool_calls": tool_calls, "done": False}
    else:
        payload = {"narration": final, "tool_calls": [], "done": True}
    return ChatResponse(
        content=json.dumps(payload, ensure_ascii=False),
        finish_reason="stop",
        # Match the common legacy execute-fake usage (15/25/40) so migrated cost assertions shift
        # predictably: the spine runs one extra (done) turn per task vs the FSM's single call.
        usage=TokenUsage(15, 25, 40),
        model_provider="fake",
        model_name=model_name,
        raw_response={},
    )
