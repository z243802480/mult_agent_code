from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from asteria_runtime.models.base import ChatRequest


# Strong models (glm-5 / glm-5.2) stream noticeably slower than the medium baseline
# (minimax) that the worker/repair role contracts are calibrated for. When an
# execution/repair role is escalated above its medium-calibrated baseline to the
# strong tier, give the per-call deadline proportional headroom so a slow-but-
# completing strong call is not aborted as a provider_timeout. Roles whose contract
# is already calibrated for strong (goal_spec/planner/review/brainstorm) keep their
# deliberate deadlines. See docs/zh/plans/发布计划-首个可发布版本.md M2.
_STRONG_TIER_DEADLINE_HEADROOM = 1.7


@dataclass(frozen=True)
class EffectiveModelDeadline:
    provider_call_seconds: int
    stream_idle_timeout_seconds: int


def effective_model_deadline(
    request: ChatRequest,
    *,
    default_provider_call_seconds: int,
    default_stream_idle_timeout_seconds: int,
) -> EffectiveModelDeadline:
    contract = _role_contract(request)
    baseline_provider_call_seconds = _apply_strong_tier_headroom(
        _positive_int(contract.get("provider_call_seconds"), default_provider_call_seconds),
        request=request,
        contract=contract,
    )
    provider_call_seconds = _positive_int(
        request.timeout_seconds,
        baseline_provider_call_seconds,
    )
    stream_idle_timeout_seconds = _positive_int(
        contract.get("stream_idle_timeout_seconds"),
        default_stream_idle_timeout_seconds,
    )
    return EffectiveModelDeadline(
        provider_call_seconds=provider_call_seconds,
        stream_idle_timeout_seconds=max(1, min(provider_call_seconds, stream_idle_timeout_seconds)),
    )


def _apply_strong_tier_headroom(
    provider_call_seconds: int,
    *,
    request: ChatRequest,
    contract: dict[str, Any],
) -> int:
    if request.model_tier != "strong":
        return provider_call_seconds
    if str(contract.get("default_model_tier")) == "strong":
        return provider_call_seconds
    return max(
        provider_call_seconds,
        math.ceil(provider_call_seconds * _STRONG_TIER_DEADLINE_HEADROOM),
    )


def _role_contract(request: ChatRequest) -> dict[str, Any]:
    contract = request.metadata.get("agent_role_contract")
    return contract if isinstance(contract, dict) else {}


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return default
