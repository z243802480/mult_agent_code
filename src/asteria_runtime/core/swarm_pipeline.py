from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.candidate_export import CandidateExporter
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.merge_gate_dry_run import MergeGateDryRunner
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.swarm_gate_audit import SwarmGateAuditor, SwarmGateAuditResult
from asteria_runtime.core.worker_spawn import record_worker_spawn_plan, plan_worker_spawns
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "exports": self.exports,
            "dry_run": self.dry_run,
            "audit": self.audit.to_dict(),
            "worker_ids": self.worker_ids,
        }


def run_maintainer_disjoint_gray_path(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict | None = None,
) -> SwarmGrayPathResult:
    """Maintainer-only gray path: S18 spawn → export → dry-run without real parallel writes."""
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
    base_task = {
        "parallel_safety": "disjoint_writes",
        "execution_profile": {"profile_id": "harness"},
        "multi_agent_strategy": {"mode": "disjoint_write_workers"},
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    tasks = [
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
    spawn_plan = plan_worker_spawns(tasks[0], policy=policy, worker_count=len(tasks))
    slots = WorkerExecutionRecorder(validator).allocate_execution_slots(context, len(tasks))
    record_worker_spawn_plan(
        context,
        plan=spawn_plan,
        task_id="task-gray-batch",
        worker_ids=[slot.worker_id for slot in slots],
    )
    _record_gray_workers(context, validator, tasks, slots)
    gateway = CandidateExecutionGateway()
    exporter = CandidateExporter(validator)
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
    )


def _record_gray_workers(
    context: RuntimeContext,
    validator: SchemaValidator,
    tasks: list[dict],
    slots: list,
) -> None:
    recorder = WorkerExecutionRecorder(validator)
    started = now_iso()
    for task, slot in zip(tasks, slots, strict=True):
        enriched = {
            **task,
            "runtime_profile_hints": {
                **dict(task.get("runtime_profile_hints") or {}),
                "spawn_kind": "harness_write",
                "fake_path": True,
                "scheduling_mode": "fake_serial",
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
            summary=f"Gray path worker completed {task['task_id']}.",
            runtime_profile_id=f"runtime-profile-gray-{task['task_id']}",
            actor="SwarmGrayPath",
        )
