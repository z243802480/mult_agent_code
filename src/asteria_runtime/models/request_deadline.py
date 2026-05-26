from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.models.base import ChatRequest


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
    provider_call_seconds = _positive_int(
        request.timeout_seconds,
        _positive_int(contract.get("provider_call_seconds"), default_provider_call_seconds),
    )
    stream_idle_timeout_seconds = _positive_int(
        contract.get("stream_idle_timeout_seconds"),
        default_stream_idle_timeout_seconds,
    )
    return EffectiveModelDeadline(
        provider_call_seconds=provider_call_seconds,
        stream_idle_timeout_seconds=max(1, min(provider_call_seconds, stream_idle_timeout_seconds)),
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
