from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, TypeVar

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_graph import ReadySelection, TaskGraphScheduler
from asteria_runtime.core.worker_recorder import WorkerExecutionSlot


T = TypeVar("T")
WorkerTaskExecutor = Callable[[dict, WorkerExecutionSlot], T]
WorkerSlotAllocator = Callable[[RuntimeContext, int], list[WorkerExecutionSlot]]


@dataclass(frozen=True)
class ExecutionCoordinator:
    max_tasks: int = 1
    parallel_readonly: bool = False
    parallel_writes: bool = False
    task_ids: frozenset[str] = frozenset()
    actor: str = "ExecutionCoordinator"

    def select_tasks(self, task_board: TaskBoard) -> ReadySelection:
        if self.task_ids:
            tasks = task_board.list_tasks()
            done = {task["task_id"] for task in tasks if task.get("status") == "done"}
            selected = [
                task
                for task in tasks
                if task.get("task_id") in self.task_ids
                and task.get("status") == "ready"
                and all(dep in done for dep in task.get("depends_on") or [])
            ][: self.max_tasks]
            return ReadySelection(
                selected=selected,
                blocked=[],
                reason="targeted_session_recovery_selection",
            )
        scheduler = TaskGraphScheduler(task_board.list_tasks())
        if self.parallel_writes:
            selection = scheduler.select_parallel_safe_batch(self.max_tasks)
            if selection.selected:
                return selection
        if self.parallel_readonly:
            selection = scheduler.select_readonly_batch(self.max_tasks)
            if selection.selected:
                return selection
        return scheduler.select_serial(self.max_tasks)

    def record_selection(self, context: RuntimeContext, selection: ReadySelection) -> None:
        if not context.event_logger:
            return
        context.event_logger.record(
            context.run_id,
            "task_graph_selection",
            self.actor,
            f"Selected {len(selection.selected)} task(s) for {selection.reason}.",
            {
                "reason": selection.reason,
                "task_ids": [task["task_id"] for task in selection.selected],
            },
        )

    def execute_selection(
        self,
        *,
        selection: ReadySelection,
        task_board: TaskBoard,
        context: RuntimeContext,
        execute_task: WorkerTaskExecutor[T],
        allocate_worker_slots: WorkerSlotAllocator,
    ) -> list[T]:
        if selection.reason in {"readonly_batch_selection", "parallel_safe_batch_selection"}:
            return self._execute_parallel_batch(
                tasks=selection.selected,
                task_board=task_board,
                context=context,
                execute_task=execute_task,
                allocate_worker_slots=allocate_worker_slots,
            )
        slots = allocate_worker_slots(context, len(selection.selected))
        results = [
            execute_task(task, slots[index]) for index, task in enumerate(selection.selected)
        ]
        task_board.promote_unblocked()
        return results

    def _execute_parallel_batch(
        self,
        *,
        tasks: list[dict],
        task_board: TaskBoard,
        context: RuntimeContext,
        execute_task: WorkerTaskExecutor[T],
        allocate_worker_slots: WorkerSlotAllocator,
    ) -> list[T]:
        if not tasks:
            return []
        slots = allocate_worker_slots(context, len(tasks))
        if len(tasks) == 1:
            result = execute_task(tasks[0], slots[0])
            task_board.promote_unblocked()
            return [result]

        results_by_task_id: dict[str, T] = {}
        with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="agent-worker") as pool:
            futures = {
                pool.submit(execute_task, task, slots[index]): task["task_id"]
                for index, task in enumerate(tasks)
            }
            for future in as_completed(futures):
                task_id = futures[future]
                results_by_task_id[task_id] = future.result()
        task_board.promote_unblocked()
        return [results_by_task_id[task["task_id"]] for task in tasks]
