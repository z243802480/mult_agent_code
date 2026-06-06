from pathlib import Path

from asteria_runtime.core.candidate_export import CandidateExporter
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_candidate_exporter_discovers_changed_files(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "out").mkdir()
    (source / "out" / "alpha.txt").write_text("old", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001", task={"write_scope": ["out/alpha.txt"]})
    (candidate.root / "out" / "alpha.txt").write_text("new", encoding="utf-8")

    exporter = CandidateExporter(SchemaValidator(Path.cwd() / "schemas"))
    files = exporter.discover_changed_files(candidate, task={"write_scope": ["out/alpha.txt"]})

    assert files == ["out/alpha.txt"]


def test_candidate_exporter_persists_schema_valid_record(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "repo"
    source.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001", task={"write_scope": ["out/beta.txt"]})
    (candidate.root / "out").mkdir(parents=True)
    (candidate.root / "out" / "beta.txt").write_text("beta", encoding="utf-8")
    context = RuntimeContext(
        root=source,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    task = {
        "task_id": "task-0001",
        "write_scope": ["out/beta.txt"],
        "parallel_safety": "disjoint_writes",
        "execution_profile": {"profile_id": "harness"},
        "runtime_profile_hints": {"spawn_kind": "harness_write", "worker_invocation_id": "worker-0001"},
    }

    export = CandidateExporter(validator).export_and_persist(
        context=context,
        candidate=candidate,
        task=task,
        changed_files=["out/beta.txt"],
    )

    assert export["export_status"] == "ready"
    assert export["execution_profile_id"] == "harness"
    records = JsonlStore(validator).read_all(run_dir / "candidate_exports.jsonl", "candidate_export")
    assert records[0]["candidate_export_id"] == export["candidate_export_id"]
    events = JsonlStore(validator).read_all(run_dir / "events.jsonl", "event")
    assert events[-1]["type"] == "candidate_exported"
