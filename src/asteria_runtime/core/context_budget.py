from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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


@dataclass(frozen=True)
class ContextEstimate:
    total_tokens: int
    sections: dict[str, int]
    duplicate_content_hashes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "sections": dict(sorted(self.sections.items())),
            "duplicate_content_hashes": list(self.duplicate_content_hashes),
        }


def estimate_request_context_tokens(messages: Iterable[Any]) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(getattr(message, "role", ""))
        total += estimate_text_tokens(getattr(message, "content", ""))
        total += 4
    return max(1, total)


def estimate_request_context(request: Any) -> ContextEstimate:
    """Estimate request context with coarse section attribution.

    The estimator intentionally stays provider-agnostic. It gives reports a stable
    explanation surface without storing raw prompt content.
    """

    sections: dict[str, int] = {}
    seen_hashes: dict[str, int] = {}
    metadata = getattr(request, "metadata", {}) or {}
    for message in getattr(request, "messages", []) or []:
        role_tokens = estimate_text_tokens(getattr(message, "role", ""))
        content = str(getattr(message, "content", "") or "")
        tokens = role_tokens + estimate_text_tokens(content) + 4
        section = _section_for_message(message, content, metadata)
        sections[section] = sections.get(section, 0) + tokens
        digest = _content_hash(content)
        if digest:
            seen_hashes[digest] = seen_hashes.get(digest, 0) + 1
    duplicate_hashes = sorted(hash_ for hash_, count in seen_hashes.items() if count > 1)
    total = max(1, sum(sections.values()))
    return ContextEstimate(
        total_tokens=total,
        sections={key: value for key, value in sections.items() if value > 0},
        duplicate_content_hashes=duplicate_hashes[:10],
    )


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


def _section_for_message(message: Any, content: str, metadata: dict[str, Any]) -> str:
    role = str(getattr(message, "role", "") or "").lower()
    lowered = content.lower()
    if role == "system":
        return "prompt_envelope" if metadata.get("prompt_envelope_hash") else "system_prompt"
    if metadata.get("context_envelope_hash") and (
        "context_envelope" in lowered or "active_goal_memory" in lowered
    ):
        return "context_envelope"
    if "tool_observation" in lowered or "tool_output" in lowered or "tool_calls" in lowered:
        return "tool_output"
    if "active_goal" in lowered or "memory" in lowered or "contextsnapshot" in lowered:
        return "memory"
    if "file" in lowered and ("path" in lowered or "content" in lowered or "excerpt" in lowered):
        return "file_excerpts"
    return "conversation"


def _content_hash(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) < 64:
        return ""
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]
