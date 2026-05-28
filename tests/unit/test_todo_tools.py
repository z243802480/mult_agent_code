import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.todo_tools import TodoReadTool, TodoWriteTool


def _context(tmp_path: Path) -> RuntimeContext:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=SchemaValidator(Path("schemas")),
    )


def test_todo_read_derives_items_from_task_plan(tmp_path: Path) -> None:
    context = _context(tmp_path)
    assert context.run_dir is not None
    (context.run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-1",
                        "title": "Implement adapter",
                        "status": "ready",
                    },
                    {
                        "task_id": "task-2",
                        "description": "Verify behavior",
                        "status": "running",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = TodoReadTool().run(context)

    assert result.ok is True
    assert result.data["source"] == "task_plan"
    assert result.data["items"] == [
        {
            "id": "task-1",
            "content": "Implement adapter",
            "status": "pending",
            "priority": "normal",
            "source_task_id": "task-1",
        },
        {
            "id": "task-2",
            "content": "Verify behavior",
            "status": "in_progress",
            "priority": "normal",
            "source_task_id": "task-2",
        },
    ]


def test_todo_write_persists_run_local_model_todos(tmp_path: Path) -> None:
    context = _context(tmp_path)

    written = TodoWriteTool().run(
        context,
        items=[
            {
                "content": "Add todo tool tests",
                "status": "done",
                "priority": "high",
            }
        ],
        reason="keep model planning state current",
    )
    read = TodoReadTool().run(context)

    assert written.ok is True
    assert written.data["path"] == ".asteria/runs/run-1/model_todos.json"
    assert read.data["source"] == "model_todos"
    assert read.data["items"][0]["status"] == "completed"
    assert read.data["items"][0]["content"] == "Add todo tool tests"
