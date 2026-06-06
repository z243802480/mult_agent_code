from dataclasses import dataclass

from pathlib import Path

from asteria_runtime.core.merge_gate_dry_run import MergeGateDryRunner
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class Verification:
    ok: bool
    summary: str = "ok"


def test_merge_gate_dry_runner_single_task_passes() -> None:
    task = {
        "task_id": "task-0001",
        "write_scope": ["out/a.txt"],
        "parallel_safety": "disjoint_writes",
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    export = {
        "candidate_export_id": "candidate-export-0001",
        "task_id": "task-0001",
        "candidate_id": "candidate-1",
        "changed_files": ["out/a.txt"],
        "export_status": "ready",
    }
    result = MergeGateDryRunner(SchemaValidator(Path.cwd() / "schemas")).evaluate_batch(
        [task],
        [export],
        {"task-0001": [Verification(ok=True)]},
    )

    assert result.ok is True
    assert result.task_results[0]["merge_gate"]["ok"] is True
    assert result.batch_violations == []


def test_merge_gate_dry_runner_detects_cross_task_file_conflict() -> None:
    base_task = {
        "parallel_safety": "disjoint_writes",
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    tasks = [
        {**base_task, "task_id": "task-0001", "write_scope": ["out/shared.txt"]},
        {**base_task, "task_id": "task-0002", "write_scope": ["out/shared.txt"]},
    ]
    exports = [
        {
            "candidate_export_id": "candidate-export-0001",
            "task_id": "task-0001",
            "changed_files": ["out/shared.txt"],
            "export_status": "ready",
        },
        {
            "candidate_export_id": "candidate-export-0002",
            "task_id": "task-0002",
            "changed_files": ["out/shared.txt"],
            "export_status": "ready",
        },
    ]
    verification = {"task-0001": [Verification(ok=True)], "task-0002": [Verification(ok=True)]}

    result = MergeGateDryRunner(SchemaValidator(Path.cwd() / "schemas")).evaluate_batch(tasks, exports, verification)

    assert result.ok is False
    assert result.batch_violations
    assert "out/shared.txt" in result.batch_violations[0]


def test_merge_gate_dry_runner_persists_record(tmp_path) -> None:
    from pathlib import Path

    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    task = {
        "task_id": "task-0001",
        "write_scope": ["out/a.txt"],
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    export = {
        "candidate_export_id": "candidate-export-0001",
        "task_id": "task-0001",
        "changed_files": ["out/a.txt"],
        "export_status": "ready",
    }
    record = MergeGateDryRunner(validator).evaluate_and_persist(
        context,
        [task],
        [export],
        {"task-0001": [Verification(ok=True)]},
    )

    assert record["dry_run"] is True
    assert record["ok"] is True
    saved = JsonlStore(validator).read_all(run_dir / "merge_gate_dry_runs.jsonl", "merge_gate_dry_run")
    assert saved[0]["merge_gate_dry_run_id"] == record["merge_gate_dry_run_id"]
