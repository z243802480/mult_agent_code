from __future__ import annotations

from asteria_runtime.core.context_budget import (
    IMAGE_TOKENS_APPROX,
    estimate_request_context,
)
from asteria_runtime.models.base import ChatMessage, ChatRequest


def _request(messages: list[ChatMessage]) -> ChatRequest:
    return ChatRequest(purpose="chat", model_tier="medium", messages=messages)


def _image_message(base64_chars: int) -> ChatMessage:
    return ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "what number is this?"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + "A" * base64_chars},
            },
        ],
    )


def test_image_payload_is_not_counted_as_prose() -> None:
    # Regression: content used to be stringified, so a 1MB image (~1.4M base64 chars) was
    # char-counted at ~350k tokens — alone enough to push context_window_ratio past the 0.9 hard
    # stop and abort the run with a fabricated "budget exhausted" reason.
    estimate = estimate_request_context(_request([_image_message(1_400_000)]))

    assert estimate.total_tokens < 10 * IMAGE_TOKENS_APPROX


def test_image_is_attributed_an_approximation_not_zero() -> None:
    with_image = estimate_request_context(_request([_image_message(1_000)])).total_tokens
    text_only = estimate_request_context(
        _request([ChatMessage(role="user", content="what number is this?")])
    ).total_tokens

    assert with_image - text_only >= IMAGE_TOKENS_APPROX


def test_text_parts_still_estimated_from_their_text() -> None:
    parts_form = estimate_request_context(
        _request([ChatMessage(role="user", content=[{"type": "text", "text": "你好 " * 200}])])
    ).total_tokens
    string_form = estimate_request_context(
        _request([ChatMessage(role="user", content="你好 " * 200)])
    ).total_tokens

    assert parts_form == string_form


def test_plain_string_content_is_unchanged() -> None:
    estimate = estimate_request_context(_request([ChatMessage(role="user", content="hello")]))
    assert estimate.total_tokens > 0
