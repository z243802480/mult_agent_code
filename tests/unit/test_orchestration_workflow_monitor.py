from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.orchestration_dynamic_runner import (
    RUNNER_STATE_FILENAME,
    RunnerStepRecord,
    append_runner_state,
)
from asteria_runtime.core.orchestration_workflow_monitor import (
    build_workflow_monitor_projection,
    project_workflow_step,
    record_workflow_step_progress,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_project_workflow_step_merge_and_isolation() -> None:
    row = {
        "step_id": "disjoint-live",
        "phase_id": "write",
        "kind": "disjoint_write_fanout",
        "status": "completed",
        "variables": {
            "merge_gate_ok": True,
            "isolation_unit_ids": ["cand-1", "cand-2"],
            "worker_ids": ["worker-0001", "worker-0002"],
        },
        "swarm_plan": {"live_execution": True, "worker_ids": ["worker-0001", "worker-0002"]},
    }
    step = project_workflow_step(row)
    assert step["merge_status"] == "passed"
    assert step["isolation_unit_ids"] == ["cand-1", "cand-2"]
    assert step["live_execution"] is True


def test_build_workflow_monitor_projection(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    state_path = run_dir / RUNNER_STATE_FILENAME
    for record in (
        RunnerStepRecord(
            step_id="read-live",
            phase_id="explore",
            kind="readonly_fanout",
            status="completed",
            variables={"worker_ids": ["worker-0001"]},
        ),
        RunnerStepRecord(
            step_id="merge-checkpoint",
            phase_id="merge",
            kind="merge_checkpoint",
            status="completed",
            variables={"merge_gate_ok": True, "workers_jsonl_present": True},
        ),
    ):
        append_runner_state(state_path, record)

    projection = build_workflow_monitor_projection(run_dir, workflow_id="wave7-l3-live-probe")
    assert projection is not None
    assert projection["workflow_id"] == "wave7-l3-live-probe"
    assert projection["step_count"] == 2
    assert projection["completed_steps"] == 2
    assert projection["merge_status"] == "passed"
    assert projection["resume_checkpoint"] == "merge-checkpoint"


def test_record_workflow_step_progress(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    validator = SchemaValidator(Path.cwd() / "schemas")
    record = RunnerStepRecord(
        step_id="readonly-live",
        phase_id="explore",
        kind="readonly_fanout",
        status="completed",
        variables={"worker_ids": ["worker-0001"]},
    )
    event = record_workflow_step_progress(
        run_dir=run_dir,
        validator=validator,
        run_id="run-test",
        record=record,
    )
    assert event is not None
    assert event.get("event_type") == "evidence"
    assert event.get("display_level") == "inspector"
    progress = json.loads((run_dir / "user_progress.jsonl").read_text(encoding="utf-8").strip())
    assert progress["data"]["workflow_step"]["step_id"] == "readonly-live"
