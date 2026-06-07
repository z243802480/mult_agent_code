"""L3 dynamic orchestration runner (CC Dynamic Workflows mechanism, not JS runtime).

CC alignment:
- Plan lives in orchestration_manifest.json (executable manifest), not AgentLoop context.
- Intermediate results live in runner state JSONL (script-side variables).
- Concurrency capped by policy max_parallel_workers_per_run (default 16).
- Supports checkpoint/resume without replaying completed steps into the main loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from asteria_runtime.core.swarm_orchestrator import plan_swarm_from_tasks
from asteria_runtime.utils.time import now_iso

if TYPE_CHECKING:
    from asteria_runtime.storage.schema_validator import SchemaValidator

from asteria_runtime.core.orchestration_dynamic_live import VERIFIER_KINDS

LIVE_FANOUT_KINDS = frozenset({"readonly_fanout", "disjoint_write_fanout", *VERIFIER_KINDS})

DEFAULT_MAX_PARALLEL_WORKERS = 16
RUNNER_STATE_FILENAME = "orchestration_runner_state.jsonl"
MANIFEST_CONTEXT_BYTES_BUDGET = 512


@dataclass(frozen=True)
class OrchestrationStep:
    step_id: str
    kind: str
    task: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationStep:
        tasks_raw = payload.get("tasks") or []
        tasks = [item for item in tasks_raw if isinstance(item, dict)]
        task = payload.get("task") if isinstance(payload.get("task"), dict) else None
        return cls(
            step_id=str(payload.get("step_id") or ""),
            kind=str(payload.get("kind") or "sequential_task"),
            task=task,
            tasks=tasks,
        )


@dataclass(frozen=True)
class OrchestrationPhase:
    phase_id: str
    steps: list[OrchestrationStep]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationPhase:
        steps_raw = payload.get("steps") or []
        steps = [OrchestrationStep.from_dict(item) for item in steps_raw if isinstance(item, dict)]
        return cls(phase_id=str(payload.get("phase_id") or ""), steps=steps)


@dataclass(frozen=True)
class OrchestrationManifest:
    workflow_id: str
    description: str
    phases: list[OrchestrationPhase]
    max_concurrent_steps: int = 4
    schema_version: str = "0.1.0"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OrchestrationManifest:
        phases_raw = payload.get("phases") or []
        phases = [OrchestrationPhase.from_dict(item) for item in phases_raw if isinstance(item, dict)]
        return cls(
            schema_version=str(payload.get("schema_version") or "0.1.0"),
            workflow_id=str(payload.get("workflow_id") or ""),
            description=str(payload.get("description") or ""),
            max_concurrent_steps=max(1, int(payload.get("max_concurrent_steps") or 4)),
            phases=phases,
        )

    def total_steps(self) -> int:
        return sum(len(phase.steps) for phase in self.phases)

    def context_footprint_hint(self) -> dict[str, Any]:
        """Manifest summary for events — not full plan injected into AgentLoop."""
        return {
            "workflow_id": self.workflow_id,
            "phase_count": len(self.phases),
            "step_count": self.total_steps(),
            "max_concurrent_steps": self.max_concurrent_steps,
            "description_chars": len(self.description),
            "context_budget_bytes": MANIFEST_CONTEXT_BYTES_BUDGET,
        }


def load_orchestration_manifest(path: Path) -> OrchestrationManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Orchestration manifest must be a JSON object.")
    manifest = OrchestrationManifest.from_dict(payload)
    if not manifest.workflow_id:
        raise ValueError("Orchestration manifest requires workflow_id.")
    if not manifest.phases:
        raise ValueError("Orchestration manifest requires at least one phase.")
    for phase in manifest.phases:
        if not phase.phase_id:
            raise ValueError("Each phase requires phase_id.")
        for step in phase.steps:
            if not step.step_id:
                raise ValueError("Each step requires step_id.")
    return manifest


def resolve_max_concurrent_steps(manifest: OrchestrationManifest, policy: dict[str, Any] | None) -> int:
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    cap = max(1, int(agent_loop.get("max_parallel_workers_per_run", DEFAULT_MAX_PARALLEL_WORKERS)))
    return min(manifest.max_concurrent_steps, cap)


@dataclass(frozen=True)
class RunnerStepRecord:
    step_id: str
    phase_id: str
    kind: str
    status: str
    swarm_plan: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    error: str | None = None
    recorded_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "phase_id": self.phase_id,
            "kind": self.kind,
            "status": self.status,
            "swarm_plan": self.swarm_plan,
            "variables": self.variables,
            "error": self.error,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunnerStepRecord:
        return cls(
            step_id=str(payload.get("step_id") or ""),
            phase_id=str(payload.get("phase_id") or ""),
            kind=str(payload.get("kind") or ""),
            status=str(payload.get("status") or ""),
            swarm_plan=payload.get("swarm_plan") if isinstance(payload.get("swarm_plan"), dict) else None,
            variables=payload.get("variables") if isinstance(payload.get("variables"), dict) else None,
            error=str(payload.get("error")) if payload.get("error") else None,
            recorded_at=str(payload.get("recorded_at") or now_iso()),
        )


def load_runner_state(path: Path) -> dict[str, RunnerStepRecord]:
    if not path.exists():
        return {}
    records: dict[str, RunnerStepRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        record = RunnerStepRecord.from_dict(payload)
        records[record.step_id] = record
    return records


def append_runner_state(path: Path, record: RunnerStepRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def _fanout_tasks(step: OrchestrationStep) -> list[dict[str, Any]]:
    if step.tasks:
        return list(step.tasks)
    if step.task:
        return [step.task]
    return []


def _plan_step_swarm(
    step: OrchestrationStep,
    *,
    policy: dict[str, Any] | None,
    parent_task_id: str,
) -> dict[str, Any] | None:
    kind = step.kind
    if kind in {"merge_checkpoint", "sequential_task"} or kind in VERIFIER_KINDS:
        return None
    tasks = _fanout_tasks(step)
    if not tasks:
        return None
    execution = plan_swarm_from_tasks(
        tasks,
        policy=policy,
        parent_task_id=parent_task_id,
    )
    return execution.to_dict()


@dataclass(frozen=True)
class DynamicOrchestrationRunResult:
    ok: bool
    workflow_id: str
    completed_steps: int
    total_steps: int
    state_path: Path
    resume_checkpoint: str | None
    dry_run: bool
    max_concurrent_steps: int
    manifest_footprint: dict[str, Any]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "workflow_id": self.workflow_id,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "state_path": str(self.state_path),
            "resume_checkpoint": self.resume_checkpoint,
            "dry_run": self.dry_run,
            "max_concurrent_steps": self.max_concurrent_steps,
            "manifest_footprint": self.manifest_footprint,
            "summary": self.summary,
        }


def run_dynamic_orchestration(
    *,
    manifest_path: Path,
    run_dir: Path,
    policy: dict[str, Any] | None = None,
    dry_run: bool = True,
    resume: bool = True,
    root: Path | None = None,
    validator: SchemaValidator | None = None,
    run_id: str | None = None,
) -> DynamicOrchestrationRunResult:
    """Execute manifest phases; state persisted under run_dir, not AgentLoop context."""
    if not dry_run and (root is None or validator is None):
        raise ValueError("Live orchestration requires root and validator.")

    manifest = load_orchestration_manifest(manifest_path)
    state_path = run_dir / RUNNER_STATE_FILENAME
    existing = load_runner_state(state_path) if resume else {}
    max_concurrent = resolve_max_concurrent_steps(manifest, policy)

    completed = sum(1 for record in existing.values() if record.status == "completed")
    total = manifest.total_steps()
    last_checkpoint: str | None = None
    failed = False
    prior_variables: list[dict[str, Any]] = [
        record.variables for record in existing.values() if isinstance(record.variables, dict)
    ]
    effective_run_id = run_id or f"run-l3-{manifest.workflow_id}"

    for phase in manifest.phases:
        pending_steps = [
            step
            for step in phase.steps
            if existing.get(step.step_id) is None or existing[step.step_id].status != "completed"
        ]
        batch_start = 0
        while batch_start < len(pending_steps):
            batch = pending_steps[batch_start : batch_start + max_concurrent]
            for step in batch:
                prior = existing.get(step.step_id)
                if prior and prior.status == "completed":
                    continue

                parent_id = f"{manifest.workflow_id}:{phase.phase_id}:{step.step_id}"
                swarm_plan = _plan_step_swarm(step, policy=policy, parent_task_id=parent_id)

                if not dry_run and step.kind in LIVE_FANOUT_KINDS.union({"merge_checkpoint"}):
                    from asteria_runtime.core.orchestration_dynamic_live import execute_live_step

                    live_result = execute_live_step(
                        step_kind=step.kind,
                        root=root,  # type: ignore[arg-type]
                        run_dir=run_dir,
                        run_id=effective_run_id,
                        validator=validator,  # type: ignore[arg-type]
                        tasks=_fanout_tasks(step),
                        parent_task_id=parent_id,
                        policy=policy,
                        prior_variables=prior_variables,
                    )
                    live_ok = live_result.get("ok") is True
                    variables = live_result.get("variables") if isinstance(live_result.get("variables"), dict) else live_result
                    if isinstance(variables, dict):
                        prior_variables.append(variables)
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="completed" if live_ok else "failed",
                        swarm_plan={**live_result, "dry_run": False, "live_execution": True},
                        variables=variables if isinstance(variables, dict) else {"live": live_result},
                        error=None if live_ok else str(live_result.get("error") or "Live step failed."),
                    )
                    if step.kind == "merge_checkpoint" and live_ok:
                        last_checkpoint = step.step_id
                elif dry_run and step.kind in VERIFIER_KINDS:
                    from asteria_runtime.core.orchestration_dynamic_live import execute_verifier_fanout_dry

                    dry_result = execute_verifier_fanout_dry(tasks=_fanout_tasks(step))
                    dry_ok = dry_result.get("ok") is True
                    variables = dry_result.get("variables") if isinstance(dry_result.get("variables"), dict) else {}
                    if isinstance(variables, dict):
                        prior_variables.append(variables)
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="completed" if dry_ok else "failed",
                        swarm_plan={**dry_result, "dry_run": True},
                        variables=variables if isinstance(variables, dict) else None,
                        error=None if dry_ok else "Adversarial verifier gate failed.",
                    )
                elif step.kind == "merge_checkpoint":
                    from asteria_runtime.core.orchestration_dynamic_live import execute_merge_checkpoint_live

                    merge_result = execute_merge_checkpoint_live(
                        run_dir=run_dir,
                        prior_variables=prior_variables,
                    )
                    merge_ok = merge_result.get("ok") is True
                    variables = merge_result.get("variables") if isinstance(merge_result.get("variables"), dict) else {}
                    if isinstance(variables, dict):
                        prior_variables.append(variables)
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="completed" if merge_ok else "failed",
                        swarm_plan={**merge_result, "dry_run": dry_run},
                        variables=variables if isinstance(variables, dict) else None,
                        error=None if merge_ok else "Merge checkpoint failed.",
                    )
                    if merge_ok:
                        last_checkpoint = step.step_id
                elif swarm_plan is None and step.kind == "sequential_task":
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="completed",
                        swarm_plan={"task": step.task, "dry_run": dry_run},
                    )
                elif swarm_plan is None:
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="failed",
                        error=f"No tasks for fanout step {step.step_id}.",
                    )
                    failed = True
                else:
                    record = RunnerStepRecord(
                        step_id=step.step_id,
                        phase_id=phase.phase_id,
                        kind=step.kind,
                        status="completed" if dry_run else "planned",
                        swarm_plan={**swarm_plan, "dry_run": dry_run},
                    )

                append_runner_state(state_path, record)
                existing[step.step_id] = record
                if not dry_run and validator is not None:
                    from asteria_runtime.core.orchestration_workflow_monitor import (
                        record_workflow_step_progress,
                    )

                    record_workflow_step_progress(
                        run_dir=run_dir,
                        validator=validator,
                        run_id=effective_run_id,
                        record=record,
                    )
                if record.status == "completed":
                    completed += 1
                else:
                    failed = True
                    break
            if failed:
                break
            batch_start += max_concurrent
        if failed:
            break

    if last_checkpoint is None:
        for record in existing.values():
            if record.kind == "merge_checkpoint" and record.status == "completed":
                last_checkpoint = record.step_id

    ok = not failed and completed == total
    summary = (
        f"L3 dynamic orchestration {'completed' if ok else 'failed'}: "
        f"{completed}/{total} steps (dry_run={dry_run})."
    )
    return DynamicOrchestrationRunResult(
        ok=ok,
        workflow_id=manifest.workflow_id,
        completed_steps=completed,
        total_steps=total,
        state_path=state_path,
        resume_checkpoint=last_checkpoint,
        dry_run=dry_run,
        max_concurrent_steps=max_concurrent,
        manifest_footprint=manifest.context_footprint_hint(),
        summary=summary,
    )
