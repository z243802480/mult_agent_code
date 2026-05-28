from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable


@dataclass(frozen=True)
class ContextPressure:
    estimated_tokens: int
    window_tokens: int
    ratio: float
    status: str
    compaction_threshold: float
    hard_stop_threshold: float

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "window_tokens": self.window_tokens,
            "ratio": self.ratio,
            "status": self.status,
            "compaction_threshold": self.compaction_threshold,
            "hard_stop_threshold": self.hard_stop_threshold,
        }


def estimate_request_context_tokens(messages: Iterable[Any]) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(getattr(message, "role", ""))
        total += estimate_text_tokens(getattr(message, "content", ""))
        total += 4
    return max(1, total)


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        codepoint = ord(char)
        if (
            0x4E00 <= codepoint <= 0x9FFF
            or 0x3400 <= codepoint <= 0x4DBF
            or 0x3040 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
        ):
            cjk += 1
        else:
            other += 1
    return cjk + ceil(other / 4)


def context_pressure(policy: dict, estimated_tokens: int) -> ContextPressure:
    context = policy.get("context") or {}
    window_tokens = max(1, int(context.get("model_context_window_tokens", 200_000)))
    compaction_threshold = float(context.get("compaction_threshold", 0.75))
    hard_stop_threshold = float(context.get("hard_stop_threshold", 0.9))
    ratio = max(0.0, estimated_tokens / window_tokens)
    if ratio >= 1:
        status = "exceeded"
    elif ratio >= hard_stop_threshold:
        status = "hard_stop"
    elif ratio >= compaction_threshold:
        status = "near_limit"
    else:
        status = "within_budget"
    return ContextPressure(
        estimated_tokens=estimated_tokens,
        window_tokens=window_tokens,
        ratio=ratio,
        status=status,
        compaction_threshold=compaction_threshold,
        hard_stop_threshold=hard_stop_threshold,
    )
