from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.utils.time import now_iso


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    status: str | None = None


class Tool(Protocol):
    name: str

    def run(self, context: RuntimeContext, **kwargs: Any) -> ToolResult:
        ...


def record_tool_call(
    context: RuntimeContext,
    tool_name: str,
    input_summary: str,
    result: ToolResult,
    task_id: str | None = None,
    agent_id: str | None = None,
    started_at: str | None = None,
) -> None:
    started = started_at or now_iso()
    ended = now_iso()
    status = result.status or ("success" if result.ok else "failure")
    record = {
        "schema_version": "0.1.0",
        "tool_call_id": "toolcall-0000",
        "run_id": context.run_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "tool_name": tool_name,
        "input_summary": input_summary,
        "output_summary": result.summary,
        "status": status,
        "started_at": started,
        "ended_at": ended,
        "error": result.error,
    }

    if context.run_dir:
        path = context.run_dir / "tool_calls.jsonl"
        store = context.tool_call_store()
        if store is None:
            return
        existing = store.read_all(path) if path.exists() else []
        record["tool_call_id"] = f"toolcall-{len(existing) + 1:04d}"
        store.append(path, record, "tool_call")

    if context.event_logger:
        context.event_logger.record(
            context.run_id,
            "tool_called",
            tool_name,
            result.summary,
            {
                "tool_name": tool_name,
                "ok": result.ok,
                "input_summary": input_summary,
                "warnings": result.warnings,
                "error": result.error,
            },
        )
