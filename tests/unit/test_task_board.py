from pathlib import Path

import pytest

from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.storage.schema_validator import SchemaValidator


def sample_task(
    task_id: str = "task-0001", status: str = "ready", depends_on: list[str] | None = None
) -> dict:
    return {
        "schema_version": "0.1.0",
        "task_id": task_id,
        "title": "Implement something",
        "description": "A useful implementation task",
        "status": status,
        "priority": "high",
        "role": "CoderAgent",
        "depends_on": depends_on or [],
        "acceptance": ["It works"],
        "allowed_tools": ["read_file"],
        "expected_artifacts": ["src/example.py"],
        "assigned_agent_id": None,
        "created_at": "2026-04-27T00:00:00+08:00",
        "updated_at": "2026-04-27T00:00:00+08:00",
        "notes": "",
    }


def test_task_board_adds_and_transitions_task(tmp_path: Path) -> None:
    board = TaskBoard(tmp_path / "backlog.json", SchemaValidator(Path("schemas")))
    board.add_task(sample_task())

    assert board.get_task("task-0001")["status"] == "ready"
    updated = board.update_status("task-0001", "in_progress")
    assert updated["status"] == "in_progress"


def test_task_board_rejects_invalid_transition(tmp_path: Path) -> None:
    board = TaskBoard(tmp_path / "backlog.json", SchemaValidator(Path("schemas")))
    board.add_task(sample_task(status="done"))

    with pytest.raises(TaskStateError):
        board.update_status("task-0001", "in_progress")


def test_task_board_completes_task_through_legal_transitions(tmp_path: Path) -> None:
    board = TaskBoard(tmp_path / "backlog.json", SchemaValidator(Path("schemas")))
    board.add_task(sample_task(status="ready"))

    board.complete_task("task-0001", "Finished cleanly.")

    task = board.get_task("task-0001")
    assert task["status"] == "done"
    assert task["notes"] == "Finished cleanly."


def test_task_board_completes_blocked_repair_task(tmp_path: Path) -> None:
    board = TaskBoard(tmp_path / "backlog.json", SchemaValidator(Path("schemas")))
    board.add_task(sample_task(status="blocked"))

    board.complete_task("task-0001")

    assert board.get_task("task-0001")["status"] == "done"


def test_task_board_ready_tasks_require_done_dependencies(tmp_path: Path) -> None:
    board = TaskBoard(tmp_path / "backlog.json", SchemaValidator(Path("schemas")))
    board.add_task(sample_task("task-0001", status="done"))
    board.add_task(sample_task("task-0002", status="ready", depends_on=["task-0001"]))
    board.add_task(sample_task("task-0003", status="ready", depends_on=["missing"]))

    ready_ids = [task["task_id"] for task in board.ready_tasks()]
    assert ready_ids == ["task-0002"]
