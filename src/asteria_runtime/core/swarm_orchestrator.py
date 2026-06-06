from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker_spawn import (
    WorkerSpawnPlan,
    plan_from_child_plan,
    plan_worker_spawns,
    record_worker_spawn_plan,
)
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


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
            "child_task_ids": [
                str(item.get("child_task_id") or item.get("task_id") or "")
                for item in self.child_tasks
            ],
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


def persist_swarm_execution_plan(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    child_plan: dict[str, Any],
    policy: dict | None = None,
) -> dict[str, Any] | None:
    """Persist orchestrator plan beside subagent_child_plan (agent loop evidence chain)."""
    children = [item for item in child_plan.get("child_tasks") or [] if isinstance(item, dict)]
    if not children:
        return None
    store = JsonlStore(validator)
    path = run_dir / "swarm_execution_plans.jsonl"
    existing = store.read_all(path, "swarm_execution_plan") if path.exists() else []
    execution = plan_swarm_execution(
        child_plan,
        policy=policy,
        parent_task_id=str(child_plan.get("parent_task_id") or ""),
    )
    record = {
        "schema_version": "0.1.0",
        "swarm_execution_plan_id": f"swarm-exec-plan-{len(existing) + 1:04d}",
        "subagent_child_plan_id": str(child_plan.get("subagent_child_plan_id") or ""),
        "run_id": str(child_plan.get("run_id") or ""),
        "parent_task_id": execution.task_id,
        "scheduling_mode": execution.spawn_plan.scheduling_mode,
        "fake_path": execution.spawn_plan.fake_path,
        "parallel_writes": execution.coordinator.parallel_writes,
        "spawn_kind": execution.spawn_plan.spawn_kind,
        "spawn_plan": execution.spawn_plan.to_dict(),
        "coordinator": {
            "max_tasks": execution.coordinator.max_tasks,
            "parallel_readonly": execution.coordinator.parallel_readonly,
            "parallel_writes": execution.coordinator.parallel_writes,
        },
        "child_task_ids": [
            str(item.get("child_task_id") or item.get("task_id") or "") for item in children
        ],
        "created_at": now_iso(),
    }
    store.append(path, record, "swarm_execution_plan")
    _record_swarm_execution_event(run_dir, validator, child_plan, execution, record)
    return record


def _record_swarm_execution_event(
    run_dir: Path,
    validator: SchemaValidator,
    child_plan: dict[str, Any],
    execution: SwarmExecutionPlan,
    record: dict[str, Any],
) -> None:
    run_id = str(child_plan.get("run_id") or "unknown-run")
    context = RuntimeContext(
        root=run_dir,
        run_id=run_id,
        policy={},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    record_swarm_execution_plan(context, execution)
    if context.event_logger is not None:
        context.event_logger.record(
            run_id,
            "swarm_execution_plan_persisted",
            "SwarmOrchestrator",
            execution.reason,
            {
                "swarm_execution_plan_id": record["swarm_execution_plan_id"],
                "subagent_child_plan_id": record["subagent_child_plan_id"],
                "scheduling_mode": record["scheduling_mode"],
                "fake_path": record["fake_path"],
            },
        )
