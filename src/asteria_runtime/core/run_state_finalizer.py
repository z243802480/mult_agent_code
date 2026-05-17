from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ExecutionFinalState:
    completed: int
    blocked: int


@dataclass(frozen=True)
class RunStateFinalizer:
    store: JsonStore
    validator: SchemaValidator
    actor: str = "RunStateFinalizer"

    def finalize(
        self,
        *,
        agent_dir: Path,
        run_dir: Path,
        run_store: RunStore,
        run: dict,
        task_board: TaskBoard,
        budget: BudgetController,
        executed: list[Any],
        cost_report_path: Path,
        event_logger: EventLogger,
    ) -> ExecutionFinalState:
        self._mirror_backlog(agent_dir, task_board)
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")

        completed = len([item for item in executed if item.status == "done"])
        blocked = len([item for item in executed if item.status == "blocked"])
        remaining_ready = task_board.ready_tasks()
        all_tasks = task_board.list_tasks()
        if self._pending_decisions(run_dir):
            run["status"] = "paused"
            run["current_phase"] = "DECISION"
            run["summary"] = "Execution paused for a user decision."
            event_logger.record(run.get("run_id"), "run_paused", self.actor, run["summary"])
        elif all(task["status"] == "done" for task in all_tasks):
            run["status"] = "completed"
            run["current_phase"] = "DONE"
            run["ended_at"] = now_iso()
            run["summary"] = "Execution completed all planned tasks."
            event_logger.record(run.get("run_id"), "run_completed", self.actor, run["summary"])
        elif blocked and not remaining_ready:
            run["status"] = "blocked"
            run["summary"] = "Execution blocked; repair or user decision is required."
            event_logger.record(run.get("run_id"), "run_blocked", self.actor, run["summary"])
        else:
            run["status"] = "running"
            run["summary"] = f"Executed {len(executed)} task(s); more work remains."
        run_store.update_run(run)
        return ExecutionFinalState(completed=completed, blocked=blocked)

    def _mirror_backlog(self, agent_dir: Path, task_board: TaskBoard) -> None:
        self.store.write(
            agent_dir / "tasks" / "backlog.json",
            {"schema_version": "0.1.0", "tasks": task_board.list_tasks()},
            "task_board",
        )

    def _pending_decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return [
            decision
            for decision in JsonlStore(self.validator).read_all(path, "decision_point")
            if decision["status"] == "pending"
        ]
