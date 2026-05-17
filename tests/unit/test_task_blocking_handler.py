from pathlib import Path

from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_blocking_handler import TaskBlockingHandler
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_blocking_handler_records_failure_and_task_execution_evidence(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    board = _board(tmp_path, validator)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )
    handler = TaskBlockingHandler(
        TaskExecutionEvidenceRecorder(validator),
        ExecutionEvidenceSink(validator, actor="BlockTest"),
        actor="BlockTest",
    )

    result = handler.block_for_failure(
        context=context,
        task_board=board,
        task=board.get_task("task-0001"),
        reason="failed",
        failure_type="exception",
    )

    assert result.status == "blocked"
    assert board.get_task("task-0001")["status"] == "blocked"
    jsonl = JsonlStore(validator)
    failures = jsonl.read_all(tmp_path / "task_failures.jsonl", "task_failure_evidence")
    evidence = jsonl.read_all(tmp_path / "task_execution_evidence.jsonl", "task_execution_evidence")
    assert failures[0]["failure_type"] == "exception"
    assert evidence[0]["status"] == "blocked"


def _board(tmp_path: Path, validator: SchemaValidator) -> TaskBoard:
    board = TaskBoard(tmp_path / "task_plan.json", validator)
    board.store.write(
        board.path,
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Task",
                    "description": "Do it",
                    "status": "in_progress",
                    "depends_on": [],
                    "allowed_tools": [],
                    "expected_artifacts": [],
                    "acceptance": [],
                    "completion_contract": {"requires_verification": False},
                    "verification_policy": {"required": False, "commands": []},
                    "parallel_safety": "serial",
                    "write_scope": [],
                    "created_at": "2026-05-17T10:00:00+08:00",
                    "updated_at": "2026-05-17T10:00:00+08:00",
                }
            ],
        },
        "task_board",
    )
    return board
