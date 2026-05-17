from pathlib import Path

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.run_state_finalizer import RunStateFinalizer
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class Summary:
    def __init__(self, status: str) -> None:
        self.status = status


def test_run_state_finalizer_completes_run_and_mirrors_backlog(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run("goal")
    run_dir = run_store.run_dir(run["run_id"])
    board = TaskBoard(run_dir / "task_plan.json", validator)
    board.store.write(
        board.path,
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Task",
                    "description": "Do it",
                    "status": "done",
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
    budget = BudgetController.from_report(
        {"cost_policy": {}},
        {
            "schema_version": "0.1.0",
            "run_id": run["run_id"],
            "model_calls": 0,
            "tool_calls": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        },
        run_id=run["run_id"],
    )

    state = RunStateFinalizer(JsonStore(validator), validator, actor="FinalizerTest").finalize(
        agent_dir=agent_dir,
        run_dir=run_dir,
        run_store=run_store,
        run=run,
        task_board=board,
        budget=budget,
        executed=[Summary("done")],
        cost_report_path=run_dir / "cost_report.json",
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
    )

    assert state.completed == 1
    assert run_store.load_run(run["run_id"])["status"] == "completed"
    assert (agent_dir / "tasks" / "backlog.json").exists()
