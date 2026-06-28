import math

from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.request_deadline import (
    _STRONG_TIER_DEADLINE_HEADROOM,
    effective_model_deadline,
)


def _request(
    *,
    model_tier: str,
    contract: dict | None = None,
    timeout_seconds: int | None = None,
) -> ChatRequest:
    metadata: dict = {}
    if contract is not None:
        metadata["agent_role_contract"] = contract
    return ChatRequest(
        purpose="task_execution",
        model_tier=model_tier,
        messages=[ChatMessage(role="user", content="Do this.")],
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )


def _coding_contract(provider_call_seconds: int = 90) -> dict:
    return {
        "role": "CoderAgent",
        "purpose": "coding",
        "default_model_tier": "medium",
        "deadline_profile": "worker",
        "provider_call_seconds": provider_call_seconds,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
    }


def test_strong_escalated_worker_gets_deadline_headroom() -> None:
    deadline = effective_model_deadline(
        _request(model_tier="strong", contract=_coding_contract(90)),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == math.ceil(90 * _STRONG_TIER_DEADLINE_HEADROOM)
    assert deadline.provider_call_seconds > 90


def test_strong_escalated_repair_gets_deadline_headroom() -> None:
    repair_contract = {
        "role": "DebugAgent",
        "purpose": "debugging",
        "default_model_tier": "medium",
        "deadline_profile": "repair",
        "provider_call_seconds": 75,
        "stream_idle_timeout_seconds": 25,
        "max_model_calls": 1,
    }

    deadline = effective_model_deadline(
        _request(model_tier="strong", contract=repair_contract),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == math.ceil(75 * _STRONG_TIER_DEADLINE_HEADROOM)


def test_strong_calibrated_role_keeps_its_deadline() -> None:
    goal_spec_contract = {
        "role": "GoalSpecAgent",
        "purpose": "goal_spec",
        "default_model_tier": "strong",
        "deadline_profile": "strong_goal_spec",
        "provider_call_seconds": 120,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
    }

    deadline = effective_model_deadline(
        _request(model_tier="strong", contract=goal_spec_contract),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == 120


def test_medium_request_is_not_given_headroom() -> None:
    deadline = effective_model_deadline(
        _request(model_tier="medium", contract=_coding_contract(90)),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == 90


def test_strong_request_without_contract_gets_headroom_on_default() -> None:
    deadline = effective_model_deadline(
        _request(model_tier="strong"),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == math.ceil(90 * _STRONG_TIER_DEADLINE_HEADROOM)


def test_explicit_request_timeout_is_authoritative_without_headroom() -> None:
    deadline = effective_model_deadline(
        _request(model_tier="strong", contract=_coding_contract(90), timeout_seconds=200),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.provider_call_seconds == 200


def test_stream_idle_timeout_is_clamped_to_provider_call_seconds() -> None:
    deadline = effective_model_deadline(
        _request(model_tier="strong", contract=_coding_contract(90)),
        default_provider_call_seconds=90,
        default_stream_idle_timeout_seconds=30,
    )

    assert deadline.stream_idle_timeout_seconds <= deadline.provider_call_seconds
    assert deadline.stream_idle_timeout_seconds == 30
