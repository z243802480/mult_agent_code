from __future__ import annotations

from asteria_runtime.core.swarm_orchestrator import plan_swarm_execution, plan_swarm_from_tasks
from asteria_runtime.core.worker_spawn import SCHEDULING_FAKE_SERIAL, SCHEDULING_PARALLEL


def _disjoint_child_plan(*, worker_count: int = 2) -> dict:
    children = []
    for index in range(worker_count):
        children.append(
            {
                "task_id": f"child-{index + 1:04d}",
                "write_scope": [f"out/file-{index + 1}.txt"],
                "parallel_safety": "disjoint_writes",
            }
        )
    return {
        "parent_task_id": "parent-0001",
        "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
        "parallel_safety": "disjoint_writes",
        "child_tasks": children,
        "coordination_policy": {"requires_disjoint_write_scope": True},
    }


def test_orchestrator_plans_fake_serial_without_flag() -> None:
    plan = plan_swarm_execution(_disjoint_child_plan(), policy={"feature_flags": {}})
    assert plan.spawn_plan.scheduling_mode == SCHEDULING_FAKE_SERIAL
    assert plan.coordinator.parallel_writes is False
    assert len(plan.child_tasks) == 2


def test_orchestrator_plans_parallel_with_probe_policy() -> None:
    from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy

    policy = with_maintainer_probe_policy({})
    plan = plan_swarm_execution(
        _disjoint_child_plan(),
        policy=policy,
        parent_task_id="parent-0001",
    )
    assert plan.spawn_plan.scheduling_mode == SCHEDULING_PARALLEL
    assert plan.coordinator.parallel_writes is True
    assert plan.task_id == "parent-0001"


def test_plan_swarm_from_tasks_matches_spawn() -> None:
    tasks = [
        {"task_id": "t1", "parallel_safety": "disjoint_writes", "write_scope": ["a.txt"]},
        {"task_id": "t2", "parallel_safety": "disjoint_writes", "write_scope": ["b.txt"]},
    ]
    plan = plan_swarm_from_tasks(tasks, policy={"feature_flags": {}})
    assert plan.spawn_plan.worker_count == 2
    assert plan.coordinator.max_tasks == 2
