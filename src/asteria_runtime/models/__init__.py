"""Model provider adapters."""

from asteria_runtime.models.base import ChatMessage, ChatRequest, ChatResponse, ModelClient
from asteria_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ModelClient",
    "MiniMaxOpenAICompatibleClient",
    "MiniMaxSettings",
]
