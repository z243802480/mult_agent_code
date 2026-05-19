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
class StreamingTelemetry:
    requested: bool = False
    supported: bool = False
    mode: str = "non_streaming"
    first_chunk_ms: int | None = None
    last_chunk_ms: int | None = None
    duration_ms: int | None = None
    chunk_count: int = 0
    idle_timeout_ms: int | None = None
    deadline_ms: int | None = None
    finish_reason: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "supported": self.supported,
            "mode": self.mode,
            "first_chunk_ms": self.first_chunk_ms,
            "last_chunk_ms": self.last_chunk_ms,
            "duration_ms": self.duration_ms,
            "chunk_count": self.chunk_count,
            "idle_timeout_ms": self.idle_timeout_ms,
            "deadline_ms": self.deadline_ms,
            "finish_reason": self.finish_reason,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class ChatResponse:
    content: str
    finish_reason: str | None
    usage: TokenUsage
    model_provider: str
    model_name: str
    raw_response: dict
    streaming: StreamingTelemetry | None = None


class ModelClient(Protocol):
    def chat(self, request: ChatRequest) -> ChatResponse:
        ...
