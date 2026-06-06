from asteria_runtime.core.execution_profile import HARNESS, SESSION_AGENT, resolve_worker_execution_profile
from asteria_runtime.core.flag_resolver import FeatureFlag
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker_recorder import WorkerExecutionSlot
from asteria_runtime.core.worker_spawn import (
    SPAWN_KIND_HARNESS_WRITE,
    SPAWN_KIND_READONLY_FANOUT,
    SCHEDULING_FAKE_SERIAL,
    SCHEDULING_PARALLEL,
    enrich_child_task,
    plan_from_child_plan,
    plan_worker_spawns,
    prepare_spawned_worker_task,
    real_disjoint_write_workers_active,
    record_worker_spawn_plan,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_resolve_worker_execution_profile_readonly_is_session_agent() -> None:
    profile = resolve_worker_execution_profile(
        {"parallel_safety": "readonly", "write_scope": [], "write_allowed": False}
    )
    assert profile.profile_id == SESSION_AGENT
    assert profile.use_replan_lineage is False


def test_resolve_worker_execution_profile_write_forces_harness() -> None:
    profile = resolve_worker_execution_profile(
        {
            "title": "Write file",
            "parallel_safety": "disjoint_writes",
            "write_scope": ["out/a.txt"],
            "write_allowed": True,
        }
    )
    assert profile.profile_id == HARNESS
    assert profile.use_replan_lineage is True


def test_plan_worker_spawns_harness_write_uses_fake_path_by_default() -> None:
    plan = plan_worker_spawns(
        {
            "parallel_safety": "disjoint_writes",
            "write_scope": ["out/a.txt", "out/b.txt"],
            "multi_agent_strategy": {"mode": "disjoint_write_workers"},
        },
        policy={"feature_flags": {"real_disjoint_write_workers": {"enabled": False}}},
        worker_count=2,
    )
    assert plan.spawn_kind == SPAWN_KIND_HARNESS_WRITE
    assert plan.execution_profile.profile_id == HARNESS
    assert plan.fake_path is True
    assert plan.scheduling_mode == SCHEDULING_FAKE_SERIAL


def test_plan_worker_spawns_real_parallel_when_flag_active() -> None:
    policy = {
        "feature_flags": {
            "real_disjoint_write_workers": FeatureFlag(
                name="real_disjoint_write_workers",
                enabled=True,
            ).to_dict()
        },
        "capability_flags": {"real_model": {"available": True}},
    }
    assert real_disjoint_write_workers_active(policy) is True
    plan = plan_worker_spawns(
        {
            "parallel_safety": "disjoint_writes",
            "write_scope": ["out/a.txt", "out/b.txt"],
        },
        policy=policy,
        worker_count=2,
    )
    assert plan.fake_path is False
    assert plan.scheduling_mode == SCHEDULING_PARALLEL


def test_plan_worker_spawns_readonly_fanout() -> None:
    plan = plan_worker_spawns(
        {
            "task_kind": "research",
            "parallel_safety": "readonly",
            "multi_agent_strategy": {"mode": "readonly_fanout"},
        },
        worker_count=3,
    )
    assert plan.spawn_kind == SPAWN_KIND_READONLY_FANOUT
    assert plan.execution_profile.profile_id == SESSION_AGENT
    assert plan.scheduling_mode == SCHEDULING_PARALLEL
    assert plan.fake_path is False


def test_plan_from_child_plan_disjoint_writes() -> None:
    child_plan = {
        "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
        "parallel_safety": "disjoint_writes",
        "child_tasks": [
            {"write_scope": ["out/a.txt"], "write_allowed": True, "parallel_safety": "disjoint_writes"},
            {"write_scope": ["out/b.txt"], "write_allowed": True, "parallel_safety": "disjoint_writes"},
        ],
    }
    plan = plan_from_child_plan(child_plan)
    assert plan.worker_count == 2
    assert plan.execution_profile.profile_id == HARNESS


def test_prepare_spawned_worker_task_sets_hints() -> None:
    plan = plan_worker_spawns(
        {"parallel_safety": "serial", "write_scope": ["out/x.txt"], "write_allowed": True},
        worker_count=1,
    )
    slot = WorkerExecutionSlot(worker_id="worker-0001", result_id="worker-result-0001")
    task = prepare_spawned_worker_task(
        {"task_id": "task-0001", "title": "Write x"},
        spawn_plan=plan,
        slot=slot,
        parent_worker_invocation_id="worker-parent",
        parent_task_id="task-parent",
        worker_kind="implementation_child",
    )
    assert task["execution_profile"]["profile_id"] == HARNESS
    hints = task["runtime_profile_hints"]
    assert hints["worker_invocation_id"] == "worker-0001"
    assert hints["parent_worker_invocation_id"] == "worker-parent"
    assert hints["spawn_kind"] == SPAWN_KIND_HARNESS_WRITE


def test_enrich_child_task_adds_execution_profile() -> None:
    parent = {
        "task_id": "task-0001",
        "parallel_safety": "disjoint_writes",
        "write_scope": ["out/a.txt", "out/b.txt"],
        "multi_agent_strategy": {"mode": "disjoint_write_workers"},
    }
    child = enrich_child_task(
        {
            "child_task_id": "task-0001-child-01",
            "write_scope": ["out/a.txt"],
            "write_allowed": True,
            "parallel_safety": "disjoint_writes",
            "worker_role": "implementation_child",
        },
        parent_task=parent,
    )
    assert child["execution_profile"]["profile_id"] == HARNESS
    assert child["runtime_profile_hints"]["worker_kind"] == "implementation_child"


def test_record_worker_spawn_plan_emits_event(tmp_path) -> None:
    from pathlib import Path

    from asteria_runtime.storage.event_logger import EventLogger
    from asteria_runtime.storage.jsonl_store import JsonlStore

    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )
    plan = plan_worker_spawns(
        {"parallel_safety": "disjoint_writes", "write_scope": ["a.txt", "b.txt"]},
        worker_count=2,
    )
    record_worker_spawn_plan(context, plan=plan, task_id="task-0001", worker_ids=["w1", "w2"])
    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert events[-1]["type"] == "worker_spawn_planned"
    assert events[-1]["data"]["spawn_plan"]["spawn_kind"] == SPAWN_KIND_HARNESS_WRITE
