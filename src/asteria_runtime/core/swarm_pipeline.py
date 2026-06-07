from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.candidate_export import CandidateExporter
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.merge_gate_dry_run import MergeGateDryRunner
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.swarm_flag_rollout import (
    evaluate_rollout_readiness,
    maintainer_probe_environment,
    with_maintainer_probe_policy,
)
from asteria_runtime.core.swarm_gate_audit import SwarmGateAuditor, SwarmGateAuditResult
from asteria_runtime.core.worker_spawn import (
    SCHEDULING_FAKE_SERIAL,
    SCHEDULING_PARALLEL,
    WorkerSpawnPlan,
    plan_worker_spawns,
    record_worker_spawn_plan,
)
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class SwarmGrayPathResult:
    run_id: str
    exports: list[dict[str, Any]]
    dry_run: dict[str, Any]
    audit: SwarmGateAuditResult
    worker_ids: list[str]
    spawn_plan: dict[str, Any]
    real_parallel: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "exports": self.exports,
            "dry_run": self.dry_run,
            "audit": self.audit.to_dict(),
            "worker_ids": self.worker_ids,
            "spawn_plan": self.spawn_plan,
            "real_parallel": self.real_parallel,
        }


def run_maintainer_disjoint_gray_path(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> SwarmGrayPathResult:
    """Maintainer-only gray path: S18 spawn → export → dry-run without real parallel writes."""
    return _run_disjoint_maintainer_path(
        root=root,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        policy=policy,
        real_parallel=False,
        tasks=tasks,
    )


def run_maintainer_real_disjoint_probe(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict | None = None,
) -> SwarmGrayPathResult:
    """Maintainer-only probe with real_disjoint_write_workers enabled in isolated policy."""
    base_policy = policy or {}
    readiness = evaluate_rollout_readiness(
        base_policy,
        target_enabled=True,
        environment=maintainer_probe_environment(),
        phase5_entry_signed=True,
    )
    if not readiness.ready:
        blockers = ", ".join(readiness.blockers) or "unknown"
        raise ValueError(f"Real disjoint probe blocked: {blockers}")
    probe_policy = with_maintainer_probe_policy(base_policy)
    return _run_disjoint_maintainer_path(
        root=root,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        policy=probe_policy,
        real_parallel=True,
        tasks=None,
    )


def run_maintainer_disjoint_tasks_path(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    tasks: list[dict[str, Any]],
    policy: dict | None = None,
    real_parallel: bool = True,
) -> SwarmGrayPathResult:
    """Maintainer disjoint path for caller-supplied tasks (L3 live orchestration band)."""
    base_policy = policy or {}
    if real_parallel:
        readiness = evaluate_rollout_readiness(
            base_policy,
            target_enabled=True,
            environment=maintainer_probe_environment(),
            phase5_entry_signed=True,
        )
        if not readiness.ready:
            blockers = ", ".join(readiness.blockers) or "unknown"
            raise ValueError(f"Real disjoint tasks path blocked: {blockers}")
        base_policy = with_maintainer_probe_policy(base_policy)
    return _run_disjoint_maintainer_path(
        root=root,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        policy=base_policy,
        real_parallel=real_parallel,
        tasks=tasks,
    )


def _run_disjoint_maintainer_path(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict | None,
    real_parallel: bool,
    tasks: list[dict[str, Any]] | None = None,
) -> SwarmGrayPathResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    context = RuntimeContext(
        root=root,
        run_id=run_id,
        policy=policy or {"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    tasks = tasks if tasks is not None else _gray_disjoint_tasks()
    spawn_plan = plan_worker_spawns(tasks[0], policy=policy, worker_count=len(tasks))
    _assert_spawn_plan(spawn_plan, real_parallel=real_parallel)
    slots = WorkerExecutionRecorder(validator).allocate_execution_slots(context, len(tasks))
    record_worker_spawn_plan(
        context,
        plan=spawn_plan,
        task_id="task-gray-batch",
        worker_ids=[slot.worker_id for slot in slots],
    )
    _record_workers(context, validator, tasks, slots, spawn_plan=spawn_plan)
    gateway = CandidateExecutionGateway()
    exports: list[dict] = []
    verification_by_task: dict[str, list] = {}
    for task, slot in zip(tasks, slots, strict=True):
        candidate = CandidateWorkspace.create(root, run_dir, task["task_id"], task=task)
        target = task["write_scope"][0]
        (candidate.root / Path(target).parent).mkdir(parents=True, exist_ok=True)
        (candidate.root / target).write_text(task["task_id"], encoding="utf-8")

        class _Ok:
            ok = True
            summary = "gray path verification passed"

        export, dry_run = gateway.preview_promotion(
            context,
            candidate,
            task,
            [target],
            [_Ok()],
            worker_invocation_id=slot.worker_id,
        )
        exports.append(export)
        verification_by_task[task["task_id"]] = [_Ok()]
        if len(exports) == 1:
            _ = dry_run

    dry_run_record = MergeGateDryRunner(validator).evaluate_and_persist(
        context,
        tasks,
        exports,
        verification_by_task,
    )
    audit = SwarmGateAuditor(validator).evaluate_run_dir(run_dir)
    return SwarmGrayPathResult(
        run_id=run_id,
        exports=exports,
        dry_run=dry_run_record,
        audit=audit,
        worker_ids=[slot.worker_id for slot in slots],
        spawn_plan=spawn_plan.to_dict(),
        real_parallel=real_parallel,
    )


def _gray_disjoint_tasks() -> list[dict]:
    base_task = {
        "parallel_safety": "disjoint_writes",
        "execution_profile": {"profile_id": "harness"},
        "multi_agent_strategy": {"mode": "disjoint_write_workers"},
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    return [
        {
            **base_task,
            "task_id": "task-gray-0001",
            "title": "Gray alpha",
            "write_scope": ["out/alpha.txt"],
            "runtime_profile_hints": {"spawn_kind": "harness_write", "worker_kind": "implementation_child"},
        },
        {
            **base_task,
            "task_id": "task-gray-0002",
            "title": "Gray beta",
            "write_scope": ["out/beta.txt"],
            "runtime_profile_hints": {"spawn_kind": "harness_write", "worker_kind": "implementation_child"},
        },
    ]


def _assert_spawn_plan(spawn_plan: WorkerSpawnPlan, *, real_parallel: bool) -> None:
    if real_parallel:
        if spawn_plan.fake_path:
            raise ValueError("Real disjoint probe requires fake_path=false.")
        if spawn_plan.scheduling_mode != SCHEDULING_PARALLEL:
            raise ValueError(
                f"Real disjoint probe requires scheduling_mode=parallel, got {spawn_plan.scheduling_mode}."
            )
        return
    if spawn_plan.scheduling_mode != SCHEDULING_FAKE_SERIAL:
        raise ValueError(
            f"Gray path requires scheduling_mode=fake_serial, got {spawn_plan.scheduling_mode}."
        )
    if not spawn_plan.fake_path:
        raise ValueError("Gray path requires fake_path=true.")


def _record_workers(
    context: RuntimeContext,
    validator: SchemaValidator,
    tasks: list[dict],
    slots: list,
    *,
    spawn_plan: WorkerSpawnPlan,
) -> None:
    recorder = WorkerExecutionRecorder(validator)
    started = now_iso()
    for task, slot in zip(tasks, slots, strict=True):
        enriched = {
            **task,
            "runtime_profile_hints": {
                **dict(task.get("runtime_profile_hints") or {}),
                "spawn_kind": spawn_plan.spawn_kind,
                "fake_path": spawn_plan.fake_path,
                "scheduling_mode": spawn_plan.scheduling_mode,
            },
        }
        recorder.record_execution(
            context=context,
            worker_id=slot.worker_id,
            result_id=slot.result_id,
            task=enriched,
            status="succeeded",
            started_at=started,
            ended_at=started,
            model_calls=0,
            tool_calls=1,
            artifact_refs=[],
            validation_refs=[],
            failure_evidence_refs=[],
            summary=f"Maintainer path worker completed {task['task_id']}.",
            runtime_profile_id=f"runtime-profile-gray-{task['task_id']}",
            actor="SwarmGrayPath" if spawn_plan.fake_path else "SwarmRealDisjointProbe",
        )
