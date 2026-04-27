from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    name: str | None = None

    def to_payload(self) -> dict:
        payload = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True)
class ChatRequest:
    purpose: str
    model_tier: str
    messages: list[ChatMessage]
    response_format: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_estimated: bool = False


@dataclass(frozen=True)
class ChatResponse:
    content: str
    finish_reason: str | None
    usage: TokenUsage
    model_provider: str
    model_name: str
    raw_response: dict


class ModelClient(Protocol):
    def chat(self, request: ChatRequest) -> ChatResponse:
        ...
