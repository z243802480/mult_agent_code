from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.task_contract import parallel_safety


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
        # Parallel disjoint writes are frozen (opt-in removed); fall back to the
        # default readonly batch so the only parallelism is readonly fanout.
        return self.select_readonly_batch(max_tasks)
