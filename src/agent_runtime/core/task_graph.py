from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.core.task_contract import parallel_safety, write_scope


@dataclass(frozen=True)
class ReadySelection:
    selected: list[dict]
    blocked: list[dict]
    reason: str


class TaskGraphScheduler:
    def __init__(self, tasks: list[dict]) -> None:
        self.tasks = tasks

    def ready_nodes(self) -> list[dict]:
        done = {task["task_id"] for task in self.tasks if task.get("status") == "done"}
        ready: list[dict] = []
        for task in self.tasks:
            dependencies = task.get("depends_on") or []
            if task.get("status") == "ready" and all(dep in done for dep in dependencies):
                ready.append(task)
        return ready

    def select_serial(self, max_tasks: int = 1) -> ReadySelection:
        ready = self.ready_nodes()
        return ReadySelection(
            selected=ready[:max_tasks],
            blocked=[],
            reason="serial_ready_selection",
        )

    def select_readonly_batch(self, max_tasks: int) -> ReadySelection:
        selected: list[dict] = []
        blocked: list[dict] = []
        for task in self.ready_nodes():
            if len(selected) >= max_tasks:
                break
            if parallel_safety(task) == "readonly":
                selected.append(task)
            else:
                blocked.append(task)
        return ReadySelection(
            selected=selected,
            blocked=blocked,
            reason="readonly_batch_selection",
        )

    def select_parallel_safe_batch(self, max_tasks: int) -> ReadySelection:
        selected: list[dict] = []
        blocked: list[dict] = []
        for task in self.ready_nodes():
            if len(selected) >= max_tasks:
                break
            safety = parallel_safety(task)
            if safety == "readonly":
                selected.append(task)
                continue
            if safety == "disjoint_writes" and not any(
                self.has_write_conflict(task, existing) for existing in selected
            ):
                selected.append(task)
                continue
            blocked.append(task)
        return ReadySelection(
            selected=selected,
            blocked=blocked,
            reason="parallel_safe_batch_selection",
        )

    def has_write_conflict(self, left: dict, right: dict) -> bool:
        left_scope = write_scope(left)
        right_scope = write_scope(right)
        return any(_scope_overlaps(left_item, right_item) for left_item in left_scope for right_item in right_scope)


def _scope_overlaps(left: str, right: str) -> bool:
    left_norm = _normalize_scope(left)
    right_norm = _normalize_scope(right)
    return left_norm == right_norm or left_norm.startswith(right_norm) or right_norm.startswith(left_norm)


def _normalize_scope(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if normalized and not normalized.endswith("/") and "." not in normalized.rsplit("/", 1)[-1]:
        normalized += "/"
    return normalized
