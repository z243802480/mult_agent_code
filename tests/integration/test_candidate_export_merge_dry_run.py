from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class Verification:
    ok: bool
    summary: str = "ok"


def test_preview_promotion_exports_and_dry_runs_without_promoting(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "repo"
    source.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    task = {
        "task_id": "task-0001",
        "write_scope": ["out/alpha.txt", "out/beta.txt"],
        "parallel_safety": "disjoint_writes",
        "execution_profile": {"profile_id": "harness"},
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
        "runtime_profile_hints": {
            "spawn_kind": "harness_write",
            "worker_invocation_id": "worker-0001",
        },
    }
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001", task=task)
    (candidate.root / "out").mkdir(parents=True)
    (candidate.root / "out" / "alpha.txt").write_text("alpha", encoding="utf-8")
    context = RuntimeContext(
        root=source,
        run_id="run-swarm-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    gateway = CandidateExecutionGateway()

    export, dry_run = gateway.preview_promotion(
        context,
        candidate,
        task,
        ["out/alpha.txt"],
        [Verification(ok=True)],
        worker_invocation_id="worker-0001",
    )

    assert export["changed_files"] == ["out/alpha.txt"]
    assert export["execution_profile_id"] == "harness"
    assert dry_run["dry_run"] is True
    assert dry_run["ok"] is True
    assert (source / "out" / "alpha.txt").exists() is False
    exports = JsonlStore(validator).read_all(run_dir / "candidate_exports.jsonl", "candidate_export")
    dry_runs = JsonlStore(validator).read_all(run_dir / "merge_gate_dry_runs.jsonl", "merge_gate_dry_run")
    assert len(exports) == 1
    assert len(dry_runs) == 1
    assert not (run_dir / "candidate_promotions.jsonl").exists()


def test_swarm_batch_dry_run_disjoint_workers(tmp_path: Path) -> None:
    from asteria_runtime.core.candidate_export import CandidateExporter
    from asteria_runtime.core.merge_gate_dry_run import MergeGateDryRunner

    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "repo"
    source.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    context = RuntimeContext(
        root=source,
        run_id="run-swarm-2",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    base = {
        "parallel_safety": "disjoint_writes",
        "execution_profile": {"profile_id": "harness"},
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
        },
    }
    tasks = [
        {**base, "task_id": "task-0001", "write_scope": ["out/alpha.txt"]},
        {**base, "task_id": "task-0002", "write_scope": ["out/beta.txt"]},
    ]
    exports = []
    exporter = CandidateExporter(validator)
    for task in tasks:
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)
        target = task["write_scope"][0]
        (candidate.root / Path(target).parent).mkdir(parents=True, exist_ok=True)
        (candidate.root / target).write_text(task["task_id"], encoding="utf-8")
        exports.append(
            exporter.export_and_persist(
                context=context,
                candidate=candidate,
                task=task,
                changed_files=[target],
            )
        )

    record = MergeGateDryRunner(validator).evaluate_and_persist(
        context,
        tasks,
        exports,
        {
            "task-0001": [Verification(ok=True)],
            "task-0002": [Verification(ok=True)],
        },
    )

    assert record["ok"] is True
    assert record["disjoint_write_gate"]["ok"] is True
    assert len(record["task_results"]) == 2
