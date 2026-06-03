from __future__ import annotations

from typing import Any


ACTIVE_TASK_STATUSES = {"ready", "in_progress", "testing", "reviewing"}
OPEN_TASK_STATUSES = ACTIVE_TASK_STATUSES | {"backlog", "blocked"}
TODO_STATUS_MAP = {
    "backlog": "pending",
    "ready": "pending",
    "in_progress": "in_progress",
    "testing": "in_progress",
    "reviewing": "in_progress",
    "blocked": "blocked",
    "done": "completed",
    "discarded": "completed",
}


def build_todo_view(
    *,
    task_plan: dict | None = None,
    model_todos: dict | None = None,
    latest_execution: dict | None = None,
    validation_conclusion: dict | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    task_items = _task_items(task_plan or {})
    model_items = _model_items(model_todos or {})
    source = "task_plan"
    items = task_items
    if model_items:
        source = "model_todos"
        items = _merge_model_items(model_items, task_items)
    counts = _counts(items)
    current = _current_item(items, latest_execution or {})
    validation = validation_conclusion or {}
    return {
        "schema_version": "0.1.0",
        "source": source if items else "empty",
        "current": current,
        "items": items[:limit],
        "counts": counts,
        "summary": _summary(counts, current, validation),
        "verification": {
            "status": str(validation.get("status") or "unknown"),
            "summary": str(validation.get("summary") or "Verification has not run yet."),
        },
    }


def todo_view_text_lines(todo_view: dict) -> list[str]:
    if not todo_view:
        return []
    lines = ["Todo:"]
    summary = str(todo_view.get("summary") or "").strip()
    if summary:
        lines.append(f"- {summary}")
    current = todo_view.get("current") or {}
    if current:
        lines.append(
            "- current: "
            f"{current.get('content') or current.get('id') or 'unknown'} "
            f"({current.get('status') or 'unknown'})"
        )
    items = [item for item in todo_view.get("items") or [] if isinstance(item, dict)]
    for item in items[:5]:
        if current and item.get("id") == current.get("id"):
            continue
        lines.append(
            "- "
            f"{item.get('content') or item.get('id') or 'untitled'} "
            f"({item.get('status') or 'unknown'})"
        )
    return lines


def _task_items(task_plan: dict) -> list[dict[str, str]]:
    tasks = task_plan.get("tasks") if isinstance(task_plan, dict) else []
    items: list[dict[str, str]] = []
    for index, task in enumerate(tasks or [], start=1):
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "backlog")
        items.append(
            {
                "id": str(task.get("task_id") or f"task-{index:04d}"),
                "content": str(task.get("title") or task.get("description") or "Untitled task"),
                "status": TODO_STATUS_MAP.get(status, "pending"),
                "task_status": status,
                "source": "task_plan",
                "source_task_id": str(task.get("task_id") or ""),
                "priority": str(task.get("priority") or "normal"),
            }
        )
    return items


def _model_items(model_todos: dict) -> list[dict[str, str]]:
    raw_items = model_todos.get("items") if isinstance(model_todos, dict) else []
    items: list[dict[str, str]] = []
    for index, item in enumerate(raw_items or [], start=1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("title") or "").strip()
        if not content:
            continue
        status = _normalize_todo_status(str(item.get("status") or "pending"))
        items.append(
            {
                "id": str(item.get("id") or f"todo-{index:04d}"),
                "content": content,
                "status": status,
                "task_status": status,
                "source": "model_todos",
                "source_task_id": str(item.get("source_task_id") or ""),
                "priority": str(item.get("priority") or "normal"),
            }
        )
    return items


def _merge_model_items(
    model_items: list[dict[str, str]],
    task_items: list[dict[str, str]],
) -> list[dict[str, str]]:
    task_by_id = {item["id"]: item for item in task_items}
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in model_items:
        source_task_id = item.get("source_task_id") or item["id"]
        task = task_by_id.get(source_task_id)
        if task:
            item = {**item, "task_status": task.get("task_status", item["task_status"])}
        merged.append(item)
        seen.add(source_task_id)
    merged.extend(item for item in task_items if item["id"] not in seen)
    return merged


def _current_item(
    items: list[dict[str, str]],
    latest_execution: dict,
) -> dict[str, str] | None:
    latest_task_id = str(latest_execution.get("task_id") or "")
    if latest_task_id:
        for item in items:
            if item.get("source_task_id") == latest_task_id or item.get("id") == latest_task_id:
                return item
    for status in ("in_progress", "pending", "blocked"):
        for item in items:
            if item.get("status") == status:
                return item
    return items[0] if items else None


def _counts(items: list[dict[str, str]]) -> dict[str, int]:
    counts = {"total": len(items), "pending": 0, "in_progress": 0, "blocked": 0, "completed": 0}
    for item in items:
        status = item.get("status") or "pending"
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
    return counts


def _summary(counts: dict[str, int], current: dict[str, str] | None, validation: dict) -> str:
    if counts["total"] == 0:
        return "No todo items recorded yet."
    if counts["completed"] == counts["total"]:
        if validation.get("status") == "passed":
            return f"All {counts['total']} todo item(s) are complete and verified."
        return f"All {counts['total']} todo item(s) are complete."
    current_text = current.get("content") if current else "next open item"
    return (
        f"{counts['completed']}/{counts['total']} complete; "
        f"current item is {current_text}."
    )


def _normalize_todo_status(status: str) -> str:
    normalized = status.strip().lower().replace("-", "_")
    if normalized in {"done", "success", "passed"}:
        return "completed"
    if normalized in {"running", "started"}:
        return "in_progress"
    if normalized in {"failed", "waiting", "needs_input"}:
        return "blocked"
    if normalized in {"pending", "in_progress", "completed", "blocked"}:
        return normalized
    return "pending"
