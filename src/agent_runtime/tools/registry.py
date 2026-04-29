from __future__ import annotations

import inspect
from typing import Any

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.budget import BudgetExceededError
from agent_runtime.tools.base import Tool, ToolResult, record_tool_call
from agent_runtime.utils.time import now_iso


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Any) -> None:
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

        sanitized_kwargs, dropped = self._sanitize_kwargs(self._tools[name], kwargs)
        try:
            result = self._tools[name].run(context, **sanitized_kwargs)
            if dropped:
                result.warnings.append(f"Ignored unsupported tool args: {', '.join(dropped)}")
        except PermissionError as exc:
            result = ToolResult(ok=False, summary=f"{name} denied by policy", error=str(exc), status="denied")
        except Exception as exc:  # noqa: BLE001 - tool boundary must convert failures to structured results
            result = ToolResult(ok=False, summary=f"{name} failed", error=str(exc))
        record_tool_call(context, name, str(sanitized_kwargs), result, task_id, agent_id, started_at)
        return result

    def _sanitize_kwargs(self, tool: Tool, kwargs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        signature = inspect.signature(tool.run)
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
            return kwargs, []
        allowed = {
            name
            for name, parameter in signature.parameters.items()
            if name != "context"
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        }
        sanitized = {key: value for key, value in kwargs.items() if key in allowed}
        dropped = sorted(key for key in kwargs if key not in allowed)
        return sanitized, dropped
