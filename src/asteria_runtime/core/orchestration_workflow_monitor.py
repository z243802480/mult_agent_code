"""L3 orchestration workflow monitor projection (S68, CC /workflows evidence client).

Studio reads orchestration_runner_state.jsonl — not a second runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.orchestration_dynamic_runner import RUNNER_STATE_FILENAME, RunnerStepRecord
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger

STATE_FILENAME = RUNNER_STATE_FILENAME


def load_runner_state_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict) and payload.get("step_id"):
            rows[str(payload["step_id"])] = payload
    return list(rows.values())


def _merge_status_from_record(record: dict[str, Any]) -> str | None:
    variables = record.get("variables") if isinstance(record.get("variables"), dict) else {}
    swarm = record.get("swarm_plan") if isinstance(record.get("swarm_plan"), dict) else {}
    if variables.get("merge_gate_ok") is True:
        return "passed"
    if variables.get("merge_gate_ok") is False:
        return "failed"
    if swarm.get("merge_status"):
        return str(swarm.get("merge_status"))
    if record.get("kind") == "merge_checkpoint":
        if variables.get("merge_gate_ok") is False:
            return "failed"
        return "passed" if record.get("status") == "completed" else "pending"
    return None


def _isolation_unit_ids(record: dict[str, Any]) -> list[str]:
    variables = record.get("variables") if isinstance(record.get("variables"), dict) else {}
    swarm = record.get("swarm_plan") if isinstance(record.get("swarm_plan"), dict) else {}
    ids: list[str] = []
    for source in (variables, swarm):
        raw = source.get("isolation_unit_ids")
        if isinstance(raw, list):
            ids.extend(str(item) for item in raw if item)
    if not ids and isinstance(swarm.get("isolation_unit_ids"), list):
        ids.extend(str(item) for item in swarm["isolation_unit_ids"] if item)
    return ids


def _verifier_status_from_record(record: dict[str, Any]) -> str | None:
    variables = record.get("variables") if isinstance(record.get("variables"), dict) else {}
    swarm = record.get("swarm_plan") if isinstance(record.get("swarm_plan"), dict) else {}
    if variables.get("verifier_passed") is True or variables.get("adversarial_ok") is True:
        return "passed"
    if variables.get("verifier_passed") is False or variables.get("adversarial_ok") is False:
        return "failed"
    if swarm.get("verifier_status"):
        return str(swarm.get("verifier_status"))
    if record.get("kind") in {"verifier_fanout", "adversarial_review"}:
        return "passed" if record.get("status") == "completed" else "failed"
    return None


def project_workflow_step(record: dict[str, Any]) -> dict[str, Any]:
    """Single step row for Studio workflow monitor."""
    variables = record.get("variables") if isinstance(record.get("variables"), dict) else {}
    return {
        "step_id": str(record.get("step_id") or ""),
        "phase_id": str(record.get("phase_id") or ""),
        "kind": str(record.get("kind") or ""),
        "status": str(record.get("status") or ""),
        "isolation_unit_ids": _isolation_unit_ids(record),
        "merge_status": _merge_status_from_record(record),
        "verifier_status": _verifier_status_from_record(record),
        "live_execution": bool((record.get("swarm_plan") or {}).get("live_execution")),
        "worker_ids": [
            str(item)
            for item in (record.get("swarm_plan") or {}).get("worker_ids") or []
            if item
        ],
        "recorded_at": str(record.get("recorded_at") or ""),
        "variables": variables,
    }


def build_workflow_monitor_projection(
    run_dir: Path,
    *,
    workflow_id: str | None = None,
) -> dict[str, Any] | None:
    """Build workflow monitor payload from runner state JSONL under run_dir."""
    state_path = run_dir / STATE_FILENAME
    rows = load_runner_state_rows(state_path)
    if not rows:
        return None

    steps = [project_workflow_step(row) for row in rows]
    steps.sort(key=lambda item: (item.get("phase_id") or "", item.get("step_id") or ""))

    completed = sum(1 for step in steps if step.get("status") == "completed")
    failed = sum(1 for step in steps if step.get("status") == "failed")
    merge_steps = [step for step in steps if step.get("kind") == "merge_checkpoint"]
    verifier_steps = [step for step in steps if step.get("kind") in {"verifier_fanout", "adversarial_review"}]
    last_merge = merge_steps[-1] if merge_steps else None
    last_verifier = verifier_steps[-1] if verifier_steps else None

    inferred_workflow_id = workflow_id
    if not inferred_workflow_id:
        for row in rows:
            swarm = row.get("swarm_plan") if isinstance(row.get("swarm_plan"), dict) else {}
            parent = str(swarm.get("task_id") or swarm.get("parent_task_id") or "")
            if ":" in parent:
                inferred_workflow_id = parent.split(":")[0]
                break

    return {
        "schema_version": "0.1.0",
        "source": "orchestration_runner_state.jsonl",
        "workflow_id": inferred_workflow_id or "unknown",
        "state_path": str(state_path),
        "step_count": len(steps),
        "completed_steps": completed,
        "failed_steps": failed,
        "resume_checkpoint": last_merge.get("step_id") if last_merge else None,
        "merge_status": last_merge.get("merge_status") if last_merge else None,
        "verifier_status": last_verifier.get("verifier_status") if last_verifier else None,
        "steps": steps,
    }


def record_workflow_step_progress(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    run_id: str,
    record: RunnerStepRecord,
) -> dict[str, Any] | None:
    """Append inspector-level user_progress for a workflow step (CC /workflows monitor)."""
    progress_path = run_dir / "user_progress.jsonl"
    step = project_workflow_step(record.to_dict())
    isolation = step.get("isolation_unit_ids") or []
    merge_status = step.get("merge_status")
    summary_parts = [f"{step['phase_id']}/{step['step_id']}", step["kind"], step["status"]]
    if isolation:
        summary_parts.append(f"isolation={','.join(isolation[:3])}")
    if merge_status:
        summary_parts.append(f"merge={merge_status}")
    verifier_status = step.get("verifier_status")
    if verifier_status:
        summary_parts.append(f"verifier={verifier_status}")

    logger = UserProgressLogger(progress_path, validator, session_id=run_id)
    progress_status = "completed" if record.status == "completed" else "failed"
    return logger.record(
        run_id=run_id,
        channel="progress",
        event_type="evidence",
        phase="execute",
        status=progress_status,
        title=f"Workflow · {record.step_id}",
        summary=" · ".join(summary_parts),
        display_level="inspector",
        transcript_kind="progress",
        ui_intent="workflow_monitor",
        evidence_refs=[str(run_dir / STATE_FILENAME)],
        data={"workflow_step": step},
    )
