from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityInvocationPolicy:
    """Describe what runtime capabilities a chat intent may ask to invoke."""

    def for_intent(self, intent: str) -> dict[str, Any]:
        if intent == "ordinary_chat":
            return self._profile(
                intent,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=[],
                reason="lightweight Ask context should not attach long-task capabilities by default",
            )
        if intent == "debug_question":
            return self._profile(
                intent,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=["runtime_inspection", "debug_context"],
                reason="debug answers may inspect mounted runtime evidence but do not execute tools",
            )
        if intent in {"progress_question", "status_question", "plan_question", "next_step_question"}:
            return self._profile(
                intent,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=["runtime_status", "goal_memory", "workspace_state"],
                reason="status and planning answers may consume durable runtime context",
            )
        return self._profile(
            intent,
            allow_tools=False,
            allow_mcp=False,
            allow_skills=False,
            groups=["runtime_context"],
            reason="unknown chat intent receives context only until explicitly promoted",
        )

    def _profile(
        self,
        intent: str,
        *,
        allow_tools: bool,
        allow_mcp: bool,
        allow_skills: bool,
        groups: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "intent": intent,
            "allow_tools": allow_tools,
            "allow_mcp": allow_mcp,
            "allow_skills": allow_skills,
            "allowed_capability_groups": groups,
            "reason": reason,
        }
