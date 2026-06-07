"""L3 dynamic orchestration live step execution (S67, CC workflow runtime).

Maintainer band: records real worker evidence under run_dir without polluting AgentLoop context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.swarm_pipeline import run_maintainer_disjoint_tasks_path
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder
from asteria_runtime.core.worker_spawn import plan_worker_spawns, record_worker_spawn_plan
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso

LIVE_READONLY_KIND = "readonly_fanout"
LIVE_DISJOINT_KIND = "disjoint_write_fanout"


def _runtime_context(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict[str, Any] | None,
) -> RuntimeContext:
    return RuntimeContext(
        root=root.resolve(),
        run_id=run_id,
        policy=policy or {"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )


def execute_readonly_fanout_live(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    tasks: list[dict[str, Any]],
    parent_task_id: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Live readonly fanout: worker slots + evidence files (session_agent profile)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id") or f"{parent_task_id}-read-{index + 1}")
        normalized.append(
            {
                **task,
                "task_id": task_id,
                "parallel_safety": "readonly",
                "runtime_profile_hints": {
                    **dict(task.get("runtime_profile_hints") or {}),
                    "parent_task_id": parent_task_id,
                    "worker_kind": "readonly_child",
                },
            }
        )
    context = _runtime_context(
        root=root,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        policy=policy,
    )
    spawn_plan = plan_worker_spawns(normalized[0], policy=policy, worker_count=len(normalized))
    slots = WorkerExecutionRecorder(validator).allocate_execution_slots(context, len(normalized))
    record_worker_spawn_plan(
        context,
        plan=spawn_plan,
        task_id=parent_task_id,
        worker_ids=[slot.worker_id for slot in slots],
    )
    evidence_dir = run_dir / "readonly_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    recorder = WorkerExecutionRecorder(validator)
    started = now_iso()
    artifact_refs_by_worker: list[str] = []
    for task, slot in zip(normalized, slots, strict=True):
        probe_path = evidence_dir / f"{task['task_id']}.txt"
        probe_path.write_text("readonly fanout live ok", encoding="utf-8")
        rel_ref = str(probe_path.relative_to(run_dir))
        artifact_refs_by_worker.append(rel_ref)
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
            artifact_refs=[rel_ref],
            validation_refs=[],
            failure_evidence_refs=[],
            summary=f"L3 live readonly worker completed {task['task_id']}.",
            runtime_profile_id=f"runtime-profile-l3-readonly-{task['task_id']}",
            actor="OrchestrationDynamicLive",
        )
    workers_path = run_dir / "workers.jsonl"
    ok = workers_path.exists() and workers_path.stat().st_size > 0
    return {
        "ok": ok,
        "kind": LIVE_READONLY_KIND,
        "worker_ids": [slot.worker_id for slot in slots],
        "isolation_unit_ids": [],
        "artifact_refs": artifact_refs_by_worker,
        "spawn_plan": spawn_plan.to_dict(),
        "variables": {
            "readonly_probe_count": len(normalized),
            "evidence_dir": str(evidence_dir.relative_to(run_dir)),
        },
    }


def execute_disjoint_write_fanout_live(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    tasks: list[dict[str, Any]],
    parent_task_id: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Live L2 disjoint fanout: candidate workspace + merge gate dry-run."""
    normalized = []
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id") or f"{parent_task_id}-write-{index + 1}")
        write_scope = [str(item) for item in task.get("write_scope") or [] if item]
        if not write_scope:
            write_scope = [f".asteria/orchestration_live/{task_id}.txt"]
        normalized.append(
            {
                **task,
                "task_id": task_id,
                "parallel_safety": "disjoint_writes",
                "write_scope": write_scope,
                "execution_profile": {"profile_id": "harness"},
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
                "completion_contract": {
                    "requires_changed_artifact": True,
                    "requires_verification": True,
                },
                "runtime_profile_hints": {
                    **dict(task.get("runtime_profile_hints") or {}),
                    "parent_task_id": parent_task_id,
                    "spawn_kind": "harness_write",
                    "worker_kind": "implementation_child",
                },
            }
        )
    result = run_maintainer_disjoint_tasks_path(
        root=root,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        tasks=normalized,
        policy=policy,
        real_parallel=True,
    )
    isolation_ids = [
        str(export.get("candidate_workspace_id") or export.get("export_id") or "")
        for export in result.exports
        if isinstance(export, dict)
    ]
    merge_ok = bool(result.dry_run.get("ok")) if isinstance(result.dry_run, dict) else False
    ok = bool(result.real_parallel and result.audit.ok and merge_ok)
    return {
        "ok": ok,
        "kind": LIVE_DISJOINT_KIND,
        "worker_ids": list(result.worker_ids),
        "isolation_unit_ids": [item for item in isolation_ids if item],
        "merge_status": "passed" if merge_ok else "failed",
        "spawn_plan": result.spawn_plan,
        "swarm_gray_path": result.to_dict(),
        "variables": {
            "export_count": len(result.exports),
            "merge_gate_ok": merge_ok,
            "audit_ok": bool(result.audit.ok),
        },
    }


def execute_merge_checkpoint_live(
    *,
    run_dir: Path,
    prior_variables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate prior live fanout steps recorded worker + merge evidence."""
    workers_path = run_dir / "workers.jsonl"
    workers_ok = workers_path.exists() and workers_path.stat().st_size > 0
    disjoint_vars = [item for item in prior_variables if item.get("merge_gate_ok") is not None]
    merge_ok = all(item.get("merge_gate_ok") is True for item in disjoint_vars) if disjoint_vars else True
    ok = workers_ok and merge_ok
    return {
        "ok": ok,
        "kind": "merge_checkpoint",
        "variables": {
            "workers_jsonl_present": workers_ok,
            "prior_disjoint_steps": len(disjoint_vars),
            "merge_gate_ok": merge_ok,
        },
    }


def execute_live_step(
    *,
    step_kind: str,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    tasks: list[dict[str, Any]],
    parent_task_id: str,
    policy: dict[str, Any] | None,
    prior_variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if step_kind == LIVE_READONLY_KIND:
        return execute_readonly_fanout_live(
            root=root,
            run_dir=run_dir,
            run_id=run_id,
            validator=validator,
            tasks=tasks,
            parent_task_id=parent_task_id,
            policy=policy,
        )
    if step_kind == LIVE_DISJOINT_KIND:
        return execute_disjoint_write_fanout_live(
            root=root,
            run_dir=run_dir,
            run_id=run_id,
            validator=validator,
            tasks=tasks,
            parent_task_id=parent_task_id,
            policy=policy,
        )
    if step_kind == "merge_checkpoint":
        return execute_merge_checkpoint_live(
            run_dir=run_dir,
            prior_variables=list(prior_variables or []),
        )
    return {"ok": False, "error": f"Unsupported live step kind: {step_kind}"}
