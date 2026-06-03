from asteria_runtime.core.todo_view import build_todo_view


def test_todo_view_merges_model_todos_with_task_plan_and_current_execution() -> None:
    view = build_todo_view(
        task_plan={
            "schema_version": "0.1.0",
            "tasks": [
                {"task_id": "task-0001", "title": "Plan work", "status": "done"},
                {"task_id": "task-0002", "title": "Implement feature", "status": "ready"},
            ],
        },
        model_todos={
            "items": [
                {
                    "id": "todo-1",
                    "content": "Implement feature",
                    "status": "in_progress",
                    "source_task_id": "task-0002",
                }
            ]
        },
        latest_execution={"task_id": "task-0002", "status": "succeeded"},
        validation_conclusion={"status": "not_recorded"},
    )

    assert view["source"] == "model_todos"
    assert view["current"]["source_task_id"] == "task-0002"
    assert view["current"]["status"] == "in_progress"
    assert view["counts"]["total"] == 2
    assert view["counts"]["completed"] == 1
    assert "1/2 complete" in view["summary"]


def test_todo_view_marks_all_complete_when_validation_passes() -> None:
    view = build_todo_view(
        task_plan={
            "tasks": [
                {"task_id": "task-0001", "title": "Implement", "status": "done"},
            ]
        },
        validation_conclusion={"status": "passed", "summary": "Validation passed."},
    )

    assert view["current"]["id"] == "task-0001"
    assert view["counts"]["completed"] == 1
    assert view["summary"] == "All 1 todo item(s) are complete and verified."
