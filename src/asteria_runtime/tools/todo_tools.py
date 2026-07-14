from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.tools.base import ToolResult


TODO_STATUSES = {"pending", "in_progress", "completed", "blocked"}


class TodoReadTool:
    name = "todo_read"

    def run(self, context: RuntimeContext) -> ToolResult:
        state = _read_todo_state(context)
        return ToolResult(
            ok=True,
            summary=f"Read {len(state['items'])} model todo items",
            data=state,
        )


class TodoWriteTool:
    name = "todo_write"

    def run(
        self,
        context: RuntimeContext,
        items: list[dict[str, Any]],
        reason: str,
    ) -> ToolResult:
        if context.run_dir is None:
            return ToolResult(
                ok=False,
                summary="todo_write requires an active run directory",
                error="missing_run_dir",
            )
        normalized = [_normalize_item(item, index) for index, item in enumerate(items, start=1)]
        if not reason.strip():
            return ToolResult(
                ok=False,
                summary="todo_write requires an update reason",
                error="missing_update_reason",
            )
        state = {
            "schema_version": "0.1.0",
            "source": "model_todo_surface",
            "run_id": context.run_id,
            "updated_by": "todo_write",
            "update_reason": reason.strip(),
            "items": normalized,
        }
        path = _todo_path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ToolResult(
            ok=True,
            summary=f"Wrote {len(normalized)} model todo items",
            data={
                "path": path.relative_to(context.root).as_posix(),
                "item_count": len(normalized),
                "items": normalized,
                # The model's own words for WHY the plan changed — the one thing that makes a
                # re-plan readable instead of a list silently mutating under the user.
                "update_reason": state["update_reason"],
            },
        )


def _read_todo_state(context: RuntimeContext) -> dict[str, Any]:
    if context.run_dir is None:
        return {
            "schema_version": "0.1.0",
            "source": "none",
            "run_id": context.run_id,
            "items": [],
            "warnings": ["No active run directory is available."],
        }
    path = _todo_path(context)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "schema_version": "0.1.0",
                "source": "damaged_model_todos",
                "run_id": context.run_id,
                "items": [],
                "warnings": ["model_todos.json is damaged and could not be parsed."],
            }
        items = loaded.get("items") if isinstance(loaded, dict) else None
        return {
            "schema_version": "0.1.0",
            "source": "model_todos",
            "run_id": context.run_id,
            "items": items if isinstance(items, list) else [],
            "warnings": [],
        }
    return _derive_from_task_plan(context)


def _derive_from_task_plan(context: RuntimeContext) -> dict[str, Any]:
    task_plan_path = context.run_dir / "task_plan.json" if context.run_dir else None
    if task_plan_path is None or not task_plan_path.exists():
        return {
            "schema_version": "0.1.0",
            "source": "empty",
            "run_id": context.run_id,
            "items": [],
            "warnings": ["No model todo state or task_plan.json exists yet."],
        }
    try:
        task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "schema_version": "0.1.0",
            "source": "damaged_task_plan",
            "run_id": context.run_id,
            "items": [],
            "warnings": ["task_plan.json is damaged and could not be parsed."],
        }
    tasks = task_plan.get("tasks") if isinstance(task_plan, dict) else None
    items = []
    for index, task in enumerate(tasks or [], start=1):
        if not isinstance(task, dict):
            continue
        items.append(
            {
                "id": str(task.get("task_id") or f"task-{index:04d}"),
                "content": str(task.get("title") or task.get("description") or "Untitled task"),
                "status": _normalize_status(str(task.get("status") or "pending")),
                "priority": str(task.get("priority") or "normal"),
                "source_task_id": str(task.get("task_id") or ""),
            }
        )
    return {
        "schema_version": "0.1.0",
        "source": "task_plan",
        "run_id": context.run_id,
        "items": items,
        "warnings": [],
    }


def _normalize_item(item: dict[str, Any], index: int) -> dict[str, str]:
    content = str(item.get("content") or item.get("title") or "").strip()
    if not content:
        raise ValueError(f"todo item {index} requires content")
    return {
        "id": str(item.get("id") or f"todo-{index:04d}"),
        "content": content,
        "status": _normalize_status(str(item.get("status") or "pending")),
        "priority": str(item.get("priority") or "normal"),
        "source_task_id": str(item.get("source_task_id") or ""),
    }


def _normalize_status(status: str) -> str:
    normalized = status.strip().lower().replace("-", "_")
    if normalized in {"done", "success", "passed"}:
        return "completed"
    if normalized in {"running", "started"}:
        return "in_progress"
    if normalized in {"failed", "waiting", "needs_input"}:
        return "blocked"
    if normalized in TODO_STATUSES:
        return normalized
    return "pending"


def _todo_path(context: RuntimeContext) -> Path:
    if context.run_dir is None:
        raise ValueError("todo state requires an active run directory")
    return context.run_dir / "model_todos.json"
