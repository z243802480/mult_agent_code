from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


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
    events = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "memory" / "recovery_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[-1]["chain"] == "damaged_memory"
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
    events = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "memory" / "recovery_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[-1]["chain"] == "multi_run_conflict"
    assert state["questions_for_user"] == [
        "Confirm which run should own the active long-task memory before accepting."
    ]
    SchemaValidator(Path("schemas")).validate("active_goal_memory", state)


def test_artifact_refs_are_not_mangled_by_prose_redaction(tmp_path: Path) -> None:
    # _clean rewrites internal jargon for human prose ("evidence" -> "work record"). It was also
    # applied to artifact_refs, whose entries are real paths the doer is told it already produced,
    # so any path containing a redacted substring was silently corrupted into a file that never
    # existed. Paths must survive verbatim.
    memory = ActiveGoalMemory(tmp_path)
    artifacts = [
        "src/evidence_utils.py",
        "tests/test_run_id_parser.py",
        ".asteria/runs/run-1/eval_report.json",
        "src/model_route_picker.py",
    ]

    memory.write_from_run(
        goal_spec=_goal(),
        task_plan=_task_plan(),
        run_status=_run("run-1"),
        review_status="unknown",
        completion="implemented_needs_review",
        artifacts=artifacts,
    )

    state = memory.read_structured()
    assert state["artifact_refs"] == artifacts
    for path in artifacts:
        assert f"- Artifact: `{path}`" in state["completed_work"]
        assert path in memory.read_user_markdown()


def test_write_rejects_a_writer_outside_the_schema_enum(tmp_path: Path) -> None:
    # active_goal.json is a persisted runtime object with a schema, but nothing validated the
    # production write path — which is how updated_by drifted outside its own enum unnoticed.
    memory = ActiveGoalMemory(tmp_path)

    with pytest.raises(SchemaValidationError):
        memory.write_from_run(
            goal_spec=_goal(),
            task_plan=_task_plan(),
            run_status=_run("run-1"),
            review_status="unknown",
            completion="implemented_needs_review",
            updated_by="not_a_known_writer",
        )

    # A rejected write must leave nothing behind, so .json and .md cannot diverge.
    assert not memory.json_path.exists()
    assert not memory.path.exists()


def test_session_continuation_is_an_accepted_writer(tmp_path: Path) -> None:
    # session_continuation.py has always written this value; the enum just never listed it.
    memory = ActiveGoalMemory(tmp_path)

    memory.write_from_run(
        goal_spec=_goal(),
        task_plan=_task_plan(),
        run_status=_run("run-1"),
        review_status="unknown",
        completion="implemented_needs_review",
        updated_by="session_continuation",
        update_reason="continued_in_session",
    )

    assert memory.read_structured()["updated_by"] == "session_continuation"
