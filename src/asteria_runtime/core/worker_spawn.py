from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.execution_profile import (
    HARNESS,
    ExecutionProfileResolution,
    resolve_worker_execution_profile,
)
from asteria_runtime.core.flag_resolver import FlagResolver
from asteria_runtime.core.multi_agent_strategy import MultiAgentStrategyAdvisor
from asteria_runtime.core.runtime_context import RuntimeContext


SPAWN_KIND_READONLY_FANOUT = "readonly_fanout"
SPAWN_KIND_HARNESS_WRITE = "harness_write"
SPAWN_KIND_SESSION_SERIAL = "session_serial"

SCHEDULING_PARALLEL = "parallel"
SCHEDULING_FAKE_SERIAL = "fake_serial"
SCHEDULING_SERIAL = "serial"

REAL_DISJOINT_WRITE_FLAG = "real_disjoint_write_workers"


@dataclass(frozen=True)
class WorkerSpawnPlan:
    spawn_kind: str
    execution_profile: ExecutionProfileResolution
    scheduling_mode: str
    fake_path: bool
    worker_count: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "spawn_kind": self.spawn_kind,
            "execution_profile": self.execution_profile.to_dict(),
            "scheduling_mode": self.scheduling_mode,
            "fake_path": self.fake_path,
            "worker_count": self.worker_count,
            "reason": self.reason,
        }


def real_disjoint_write_workers_active(policy: dict | None) -> bool:
    if not policy:
        return False
    resolution = FlagResolver.from_policy(policy).resolve(REAL_DISJOINT_WRITE_FLAG)
    return resolution is not None and resolution.active


def _spawn_kind_for_task(task: dict, strategy_mode: str) -> str:
    parallel_safety = str(task.get("parallel_safety") or "serial")
    write_scope = [str(item) for item in task.get("write_scope") or [] if item]
    if parallel_safety == "readonly" or strategy_mode == "readonly_fanout":
        return SPAWN_KIND_READONLY_FANOUT
    if parallel_safety == "disjoint_writes" and len(write_scope) >= 1:
        return SPAWN_KIND_HARNESS_WRITE
    if task.get("write_allowed") is True or write_scope:
        return SPAWN_KIND_HARNESS_WRITE
    return SPAWN_KIND_SESSION_SERIAL


def plan_worker_spawns(
    task: dict,
    *,
    policy: dict | None = None,
    worker_count: int = 1,
) -> WorkerSpawnPlan:
    """Plan how workers should spawn for a parent task (contract only; no execution)."""
    strategy = MultiAgentStrategyAdvisor().for_task(task)
    spawn_kind = _spawn_kind_for_task(task, strategy.mode)
    profile = resolve_worker_execution_profile(task)
    if spawn_kind == SPAWN_KIND_READONLY_FANOUT:
        return WorkerSpawnPlan(
            spawn_kind=spawn_kind,
            execution_profile=profile,
            scheduling_mode=SCHEDULING_PARALLEL,
            fake_path=False,
            worker_count=max(1, worker_count),
            reason="Readonly fanout may run in parallel under session_agent workers.",
        )
    if spawn_kind == SPAWN_KIND_HARNESS_WRITE:
        real_parallel = real_disjoint_write_workers_active(policy)
        if real_parallel and worker_count > 1:
            scheduling = SCHEDULING_PARALLEL
            fake_path = False
            reason = "Harness write workers run in parallel (real_disjoint_write_workers active)."
        elif worker_count > 1:
            scheduling = SCHEDULING_FAKE_SERIAL
            fake_path = True
            reason = (
                "Harness profile forced; fake_serial path records spawn contract "
                "while real_disjoint_write_workers remains disabled."
            )
        else:
            scheduling = SCHEDULING_SERIAL
            fake_path = False
            reason = "Single harness write worker runs serially."
        return WorkerSpawnPlan(
            spawn_kind=spawn_kind,
            execution_profile=profile,
            scheduling_mode=scheduling,
            fake_path=fake_path,
            worker_count=max(1, worker_count),
            reason=reason,
        )
    return WorkerSpawnPlan(
        spawn_kind=spawn_kind,
        execution_profile=profile,
        scheduling_mode=SCHEDULING_SERIAL,
        fake_path=False,
        worker_count=max(1, worker_count),
        reason="Serial session worker.",
    )


def plan_from_child_plan(child_plan: dict, *, policy: dict | None = None) -> WorkerSpawnPlan:
    children = [item for item in child_plan.get("child_tasks") or [] if isinstance(item, dict)]
    parent_parallel = str(child_plan.get("parallel_safety") or "serial")
    parent_task = {
        "parallel_safety": parent_parallel,
        "write_scope": _merged_write_scope(children),
        "multi_agent_strategy": {
            "mode": _mode_from_scheduling(str(child_plan.get("scheduling_strategy") or "")),
        },
    }
    return plan_worker_spawns(parent_task, policy=policy, worker_count=len(children) or 1)


def prepare_spawned_worker_task(
    base_task: dict,
    *,
    spawn_plan: WorkerSpawnPlan,
    slot: object | None = None,
    parent_worker_invocation_id: str | None = None,
    parent_task_id: str | None = None,
    worker_kind: str | None = None,
) -> dict:
    """Enrich a worker task with execution_profile and spawn metadata."""
    task = dict(base_task)
    task["execution_profile"] = spawn_plan.execution_profile.to_dict()
    hints = dict(task.get("runtime_profile_hints") or {})
    hints["spawn_kind"] = spawn_plan.spawn_kind
    hints["scheduling_mode"] = spawn_plan.scheduling_mode
    hints["fake_path"] = spawn_plan.fake_path
    if parent_worker_invocation_id:
        hints["parent_worker_invocation_id"] = parent_worker_invocation_id
    if parent_task_id:
        hints["parent_task_id"] = parent_task_id
    if worker_kind:
        hints["worker_kind"] = worker_kind
    if slot is not None:
        hints["worker_invocation_id"] = getattr(slot, "worker_id", None)
        hints["worker_result_id"] = getattr(slot, "result_id", None)
    task["runtime_profile_hints"] = hints
    return task


def enrich_child_task(
    child: dict,
    *,
    parent_task: dict,
    policy: dict | None = None,
) -> dict:
    plan = plan_worker_spawns(parent_task, policy=policy, worker_count=1)
    child_task = {
        **child,
        "parallel_safety": str(child.get("parallel_safety") or parent_task.get("parallel_safety") or "serial"),
        "write_scope": list(child.get("write_scope") or []),
        "write_allowed": child.get("write_allowed"),
    }
    if child_task["write_allowed"] is None:
        child_task["write_allowed"] = bool(child_task["write_scope"])
    child_plan = resolve_worker_execution_profile(child_task)
    if child_plan.profile_id == HARNESS:
        plan = WorkerSpawnPlan(
            spawn_kind=plan.spawn_kind,
            execution_profile=child_plan,
            scheduling_mode=plan.scheduling_mode,
            fake_path=plan.fake_path,
            worker_count=plan.worker_count,
            reason=plan.reason,
        )
    return prepare_spawned_worker_task(
        child_task,
        spawn_plan=plan,
        parent_task_id=str(parent_task.get("task_id") or child.get("task_id") or ""),
        worker_kind=str(child.get("worker_role") or "child"),
    )


def record_worker_spawn_plan(
    context: RuntimeContext,
    *,
    plan: WorkerSpawnPlan,
    task_id: str,
    worker_ids: list[str] | None = None,
    actor: str = "WorkerSpawn",
) -> None:
    if context.event_logger is None:
        return
    context.event_logger.record(
        context.run_id,
        "worker_spawn_planned",
        actor,
        f"Planned {plan.worker_count} worker(s) for {task_id} ({plan.spawn_kind}).",
        {
            "task_id": task_id,
            "spawn_plan": plan.to_dict(),
            "worker_ids": worker_ids or [],
        },
    )


def _merged_write_scope(children: list[dict]) -> list[str]:
    scope: list[str] = []
    for child in children:
        for item in child.get("write_scope") or []:
            text = str(item)
            if text and text not in scope:
                scope.append(text)
    return scope


def _mode_from_scheduling(scheduling: str) -> str:
    if scheduling == "parallel_readonly_safe":
        return "readonly_fanout"
    if scheduling in {"parallel_disjoint_writes_after_merge_gate", "serial_write_fallback"}:
        return "disjoint_write_workers"
    if scheduling == "serial_plan_then_execute":
        return "plan_then_serial"
    return "serial_worker"
