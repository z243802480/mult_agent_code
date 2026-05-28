from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.storage.schema_validator import SchemaValidator


def _goal() -> dict:
    return {
        "goal_id": "goal-1",
        "original_goal": "Ship durable progress memory",
        "normalized_goal": "Ship durable progress memory",
    }


def _task_plan() -> dict:
    return {
        "tasks": [
            {
                "task_id": "task-0001",
                "title": "Implement memory protocol",
                "status": "done",
                "summary": "Memory protocol implemented.",
            }
        ]
    }


def _run(run_id: str, phase: str = "DONE") -> dict:
    return {"run_id": run_id, "current_phase": phase, "status": "completed"}


def test_active_goal_memory_recovers_from_corrupt_json_with_markdown_fallback(
    tmp_path: Path,
) -> None:
    memory = ActiveGoalMemory(tmp_path)
    memory.path.parent.mkdir(parents=True)
    memory.path.write_text(
        "# Asteria Active Goal\n\n## Current Goal\n\nKeep user progress durable.\n",
        encoding="utf-8",
    )
    memory.json_path.write_text("{broken", encoding="utf-8")

    recovered = memory.read_structured()

    assert recovered["update_reason"] == "recovery_from_corrupt_json"
    assert recovered["current_goal"] == "Keep user progress durable."
    assert recovered["current_result"]["state"] == "needs repair"
    SchemaValidator(Path("schemas")).validate("active_goal_memory", recovered)


def test_active_goal_memory_marks_cross_run_conflict_without_blocking_write(
    tmp_path: Path,
) -> None:
    memory = ActiveGoalMemory(tmp_path)
    memory.write_from_run(
        goal_spec=_goal(),
        task_plan=_task_plan(),
        run_status=_run("run-old", "DONE"),
        review_status="unknown",
        completion="implemented_needs_review",
    )

    memory.write_from_run(
        goal_spec=_goal(),
        task_plan=_task_plan(),
        run_status=_run("run-new", "DONE"),
        review_status="unknown",
        completion="implemented_needs_review",
        updated_by="resume",
        update_reason="resume_applied_decisions",
    )

    state = memory.read_structured()

    assert state["source_run_id"] == "run-new"
    assert state["updated_by"] == "resume"
    assert state["update_reason"] == "resume_applied_decisions"
    assert any("previous=run-old" in item for item in state["current_blockers"])
    assert state["questions_for_user"] == [
        "Confirm which run should own the active long-task memory before accepting."
    ]
    SchemaValidator(Path("schemas")).validate("active_goal_memory", state)
