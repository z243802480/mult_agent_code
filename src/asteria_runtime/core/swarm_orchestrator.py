from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.worker_spawn import (
    WorkerSpawnPlan,
    plan_from_child_plan,
    plan_worker_spawns,
    record_worker_spawn_plan,
)


@dataclass(frozen=True)
class SwarmExecutionPlan:
    spawn_plan: WorkerSpawnPlan
    coordinator: ExecutionCoordinator
    child_tasks: list[dict[str, Any]]
    task_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "spawn_plan": self.spawn_plan.to_dict(),
            "coordinator": {
                "max_tasks": self.coordinator.max_tasks,
                "parallel_readonly": self.coordinator.parallel_readonly,
                "parallel_writes": self.coordinator.parallel_writes,
            },
            "child_task_ids": [str(item.get("task_id") or "") for item in self.child_tasks],
            "task_id": self.task_id,
            "reason": self.reason,
        }


def plan_swarm_execution(
    child_plan: dict[str, Any],
    *,
    policy: dict | None = None,
    parent_task_id: str | None = None,
) -> SwarmExecutionPlan:
    """Thin orchestrator hook: child_plan → spawn plan + ExecutionCoordinator config."""
    children = [item for item in child_plan.get("child_tasks") or [] if isinstance(item, dict)]
    task_id = str(parent_task_id or child_plan.get("parent_task_id") or "swarm-parent")
    spawn_plan = plan_from_child_plan(child_plan, policy=policy)
    parallel_writes = spawn_plan.scheduling_mode == "parallel" and not spawn_plan.fake_path
    parallel_readonly = spawn_plan.spawn_kind == "readonly_fanout"
    coordinator = ExecutionCoordinator(
        max_tasks=max(1, len(children) or spawn_plan.worker_count),
        parallel_readonly=parallel_readonly,
        parallel_writes=parallel_writes,
    )
    reason = (
        f"Swarm orchestrator planned {spawn_plan.worker_count} worker(s) "
        f"({spawn_plan.spawn_kind}, {spawn_plan.scheduling_mode})."
    )
    return SwarmExecutionPlan(
        spawn_plan=spawn_plan,
        coordinator=coordinator,
        child_tasks=children,
        task_id=task_id,
        reason=reason,
    )


def record_swarm_execution_plan(context, plan: SwarmExecutionPlan, *, actor: str = "SwarmOrchestrator") -> None:
    record_worker_spawn_plan(
        context,
        plan=plan.spawn_plan,
        task_id=plan.task_id,
        actor=actor,
    )
    if context.event_logger is None:
        return
    context.event_logger.record(
        context.run_id,
        "swarm_execution_planned",
        actor,
        plan.reason,
        plan.to_dict(),
    )


def plan_swarm_from_tasks(
    tasks: list[dict[str, Any]],
    *,
    policy: dict | None = None,
    parent_task_id: str = "swarm-batch",
) -> SwarmExecutionPlan:
    """Plan swarm execution from a flat task list (maintainer probes)."""
    if not tasks:
        raise ValueError("tasks must not be empty")
    spawn_plan = plan_worker_spawns(tasks[0], policy=policy, worker_count=len(tasks))
    parallel_writes = spawn_plan.scheduling_mode == "parallel" and not spawn_plan.fake_path
    coordinator = ExecutionCoordinator(
        max_tasks=len(tasks),
        parallel_writes=parallel_writes,
    )
    return SwarmExecutionPlan(
        spawn_plan=spawn_plan,
        coordinator=coordinator,
        child_tasks=tasks,
        task_id=parent_task_id,
        reason=f"Batch plan for {len(tasks)} disjoint task(s).",
    )
