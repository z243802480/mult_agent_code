from pathlib import Path

from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.worker_recorder import WorkerExecutionSlot
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_execution_coordinator_records_selection_event(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    board = _task_board(tmp_path, validator, [_task("task-0001", "ready")])
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )

    coordinator = ExecutionCoordinator(actor="TestCoordinator")
    selection = coordinator.select_tasks(board)
    coordinator.record_selection(context, selection)

    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert events[-1]["type"] == "task_graph_selection"
    assert events[-1]["actor"] == "TestCoordinator"
    assert events[-1]["data"]["task_ids"] == ["task-0001"]


def test_execution_coordinator_runs_parallel_batch_with_preallocated_worker_ids(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    tasks = [
        _task("task-0001", "ready", parallel_safety="readonly"),
        _task("task-0002", "ready", parallel_safety="readonly"),
    ]
    board = _task_board(tmp_path, validator, tasks)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    calls: list[tuple[str, str, str]] = []

    def execute_task(task: dict, slot: WorkerExecutionSlot) -> str:
        calls.append((task["task_id"], slot.worker_id, slot.result_id))
        return task["task_id"]

    coordinator = ExecutionCoordinator(max_tasks=2, parallel_readonly=True)
    selection = coordinator.select_tasks(board)
    results = coordinator.execute_selection(
        selection=selection,
        task_board=board,
        context=context,
        execute_task=execute_task,
        allocate_worker_slots=lambda _context, count: [
            WorkerExecutionSlot(
                worker_id=f"worker-{index:04d}",
                result_id=f"worker-result-{index:04d}",
            )
            for index in range(1, count + 1)
        ],
    )

    assert results == ["task-0001", "task-0002"]
    assert sorted(calls) == [
        ("task-0001", "worker-0001", "worker-result-0001"),
        ("task-0002", "worker-0002", "worker-result-0002"),
    ]


def test_execution_coordinator_allocates_slots_for_serial_selection(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    board = _task_board(tmp_path, validator, [_task("task-0001", "ready")])
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    calls: list[tuple[str, str, str]] = []

    def execute_task(task: dict, slot: WorkerExecutionSlot) -> str:
        calls.append((task["task_id"], slot.worker_id, slot.result_id))
        return task["task_id"]

    coordinator = ExecutionCoordinator(max_tasks=1)
    selection = coordinator.select_tasks(board)
    results = coordinator.execute_selection(
        selection=selection,
        task_board=board,
        context=context,
        execute_task=execute_task,
        allocate_worker_slots=lambda _context, count: [
            WorkerExecutionSlot("worker-0001", "worker-result-0001") for _index in range(count)
        ],
    )

    assert results == ["task-0001"]
    assert calls == [("task-0001", "worker-0001", "worker-result-0001")]


def _task(task_id: str, status: str, *, parallel_safety: str = "serial") -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "depends_on": [],
        "parallel_safety": parallel_safety,
        "write_scope": [],
    }


def _task_board(tmp_path: Path, validator: SchemaValidator, tasks: list[dict]) -> TaskBoard:
    board = TaskBoard(tmp_path / "task_plan.json", validator)
    board.store.write(
        board.path,
        {"schema_version": "0.1.0", "tasks": tasks},
        "task_board",
    )
    return board
