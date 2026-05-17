from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_worker_recorder_persists_invocation_result_and_event(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )
    recorder = WorkerExecutionRecorder(validator)

    recorder.record_execution(
        context=context,
        worker_id="worker-0001",
        result_id="worker-result-0001",
        task={"task_id": "task-0001", "role": "CoderAgent"},
        status="succeeded",
        started_at="2026-05-14T10:00:00+08:00",
        ended_at="2026-05-14T10:00:05+08:00",
        model_calls=1,
        tool_calls=2,
        artifact_refs=["artifact-0001"],
        validation_refs=["validation-0001"],
        failure_evidence_refs=[],
        summary="done",
        runtime_profile_id="runtime-profile-0001",
        actor="WorkerRecorderTest",
    )

    jsonl = JsonlStore(validator)
    workers = jsonl.read_all(tmp_path / "workers.jsonl", "worker_invocation")
    results = jsonl.read_all(tmp_path / "worker_results.jsonl", "worker_result")
    events = jsonl.read_all(tmp_path / "events.jsonl", "event")
    assert workers[0]["worker_invocation_id"] == "worker-0001"
    assert workers[0]["status"] == "succeeded"
    assert results[0]["worker_result_id"] == "worker-result-0001"
    assert results[0]["status"] == "succeeded"
    assert results[0]["cost"] == {"model_calls": 1, "tool_calls": 2}
    assert events[-1]["type"] == "worker_recorded"
    assert events[-1]["actor"] == "WorkerRecorderTest"


def test_worker_recorder_allocates_ids_from_existing_jsonl(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    recorder = WorkerExecutionRecorder(validator)
    (tmp_path / "workers.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    (tmp_path / "worker_results.jsonl").write_text("{}\n", encoding="utf-8")

    assert recorder.allocate_worker_ids(context, 2) == ["worker-0003", "worker-0004"]
    assert recorder.allocate_worker_result_ids(context, 2) == [
        "worker-result-0002",
        "worker-result-0003",
    ]
