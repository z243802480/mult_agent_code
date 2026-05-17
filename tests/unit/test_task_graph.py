from asteria_runtime.core.task_graph import TaskGraphScheduler


def test_task_graph_scheduler_selects_ready_nodes_serially() -> None:
    tasks = [
        {"task_id": "task-0001", "status": "done", "depends_on": []},
        {"task_id": "task-0002", "status": "ready", "depends_on": ["task-0001"]},
        {"task_id": "task-0003", "status": "ready", "depends_on": ["missing"]},
    ]

    selection = TaskGraphScheduler(tasks).select_serial(max_tasks=1)

    assert [task["task_id"] for task in selection.selected] == ["task-0002"]
    assert selection.reason == "serial_ready_selection"


def test_task_graph_scheduler_selects_readonly_batch() -> None:
    tasks = [
        {
            "task_id": "task-0001",
            "status": "ready",
            "depends_on": [],
            "task_kind": "research",
        },
        {
            "task_id": "task-0002",
            "status": "ready",
            "depends_on": [],
            "task_kind": "implementation",
            "expected_changed_files": ["src/app.py"],
        },
    ]

    selection = TaskGraphScheduler(tasks).select_readonly_batch(max_tasks=2)

    assert [task["task_id"] for task in selection.selected] == ["task-0001"]
    assert [task["task_id"] for task in selection.blocked] == ["task-0002"]


def test_task_graph_scheduler_selects_disjoint_write_batch_without_conflicts() -> None:
    tasks = [
        {
            "task_id": "task-0001",
            "status": "ready",
            "depends_on": [],
            "parallel_safety": "disjoint_writes",
            "write_scope": ["src/a.py"],
        },
        {
            "task_id": "task-0002",
            "status": "ready",
            "depends_on": [],
            "parallel_safety": "disjoint_writes",
            "write_scope": ["src/b.py"],
        },
        {
            "task_id": "task-0003",
            "status": "ready",
            "depends_on": [],
            "parallel_safety": "disjoint_writes",
            "write_scope": ["src/"],
        },
        {
            "task_id": "task-0004",
            "status": "ready",
            "depends_on": [],
            "parallel_safety": "serial",
            "write_scope": ["docs/"],
        },
    ]

    selection = TaskGraphScheduler(tasks).select_parallel_safe_batch(max_tasks=4)

    assert [task["task_id"] for task in selection.selected] == ["task-0001", "task-0002"]
    assert [task["task_id"] for task in selection.blocked] == ["task-0003", "task-0004"]
    assert selection.reason == "parallel_safe_batch_selection"


def test_task_graph_scheduler_detects_write_scope_conflict() -> None:
    scheduler = TaskGraphScheduler([])

    assert scheduler.has_write_conflict(
        {"expected_changed_files": ["src/asteria_runtime/"]},
        {"expected_changed_files": ["src/asteria_runtime/commands/execute_command.py"]},
    )
    assert not scheduler.has_write_conflict(
        {"expected_changed_files": ["src/asteria_runtime/core/"]},
        {"expected_changed_files": ["docs/zh/"]},
    )
