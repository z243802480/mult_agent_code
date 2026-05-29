from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.disjoint_write_gate import DisjointWriteGate
from asteria_runtime.core.task_contract import parallel_safety


@dataclass(frozen=True)
class ReadySelection:
    selected: list[dict]
    blocked: list[dict]
    reason: str


class TaskGraphScheduler:
    def __init__(self, tasks: list[dict]) -> None:
        self.tasks = tasks
        self.disjoint_write_gate = DisjointWriteGate()

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
            write_batch = [
                existing for existing in selected if parallel_safety(existing) == "disjoint_writes"
            ]
            if (
                safety == "disjoint_writes"
                and self.disjoint_write_gate.allows([*write_batch, task])
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
        return self.disjoint_write_gate.has_write_conflict(left, right)
