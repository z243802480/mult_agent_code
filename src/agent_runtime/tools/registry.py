from __future__ import annotations

from typing import Any

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.budget import BudgetExceededError
from agent_runtime.tools.base import Tool, ToolResult, record_tool_call
from agent_runtime.utils.time import now_iso


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(
        self,
        name: str,
        context: RuntimeContext,
        task_id: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        started_at = now_iso()
        if context.budget:
            try:
                context.budget.record_tool_call()
            except BudgetExceededError as exc:
                result = ToolResult(
                    ok=False,
                    summary="Tool call denied by budget",
                    error=str(exc),
                    status="denied",
                )
                record_tool_call(context, name, str(kwargs), result, task_id, agent_id, started_at)
                return result

        if name not in self._tools:
            result = ToolResult(ok=False, summary=f"Unknown tool: {name}", error="unknown_tool")
            record_tool_call(context, name, str(kwargs), result, task_id, agent_id, started_at)
            return result

        try:
            result = self._tools[name].run(context, **kwargs)
        except PermissionError as exc:
            result = ToolResult(ok=False, summary=f"{name} denied by policy", error=str(exc), status="denied")
        except Exception as exc:  # noqa: BLE001 - tool boundary must convert failures to structured results
            result = ToolResult(ok=False, summary=f"{name} failed", error=str(exc))
        record_tool_call(context, name, str(kwargs), result, task_id, agent_id, started_at)
        return result
