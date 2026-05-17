from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_task_plan_quality_gate_auto_revises_simple_plan_failures(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("asteria plan weak goal")
    run_dir = run_store.run_dir(run["run_id"])
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-1",
        "original_goal": "create a small Python CLI",
        "normalized_goal": "Create a small Python CLI.",
        "goal_type": "software_tool",
        "assumptions": [],
        "constraints": [],
        "non_goals": [],
        "expanded_requirements": [
            {
                "id": "req-1",
                "priority": "must",
                "description": "Create the CLI.",
                "source": "user",
                "acceptance": [],
            }
        ],
        "target_outputs": ["tool.py"],
        "definition_of_done": ["tool.py exists and can be run"],
        "verification_strategy": ["python tool.py --help"],
        "budget": {},
    }
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [
            {
                "schema_version": "0.1.0",
                "task_id": "task-0001",
                "title": "Build CLI",
                "description": "Create a small Python command line tool.",
                "status": "backlog",
                "priority": "high",
                "role": "CoderAgent",
                "depends_on": ["missing-task"],
                "acceptance": [],
                "allowed_tools": ["read_file"],
                "expected_artifacts": [],
                "task_kind": "implementation",
                "expected_changed_files": [],
                "assigned_agent_id": None,
                "created_at": "2026-05-08T10:00:00+08:00",
                "updated_at": "2026-05-08T10:00:00+08:00",
                "verification_policy": {"required": True, "commands": ["python tool.py --help"]},
            }
        ],
    }
    store.write(run_dir / "goal_spec.json", goal_spec, "goal_spec")
    store.write(run_dir / "task_plan.json", task_plan, "task_board")

    result = TaskPlanQualityGate(tmp_path, validator).check(run["run_id"])

    assert not result.blocked
    assert result.task_plan_eval["status"] != "fail"
    revised = store.read(run_dir / "task_plan.json", "task_board")
    task = revised["tasks"][0]
    assert task["status"] == "ready"
    assert task["depends_on"] == []
    assert task["acceptance"] == ["tool.py exists and can be run"]
    assert task["expected_artifacts"] == ["tool.py"]
    assert "apply_patch" in task["allowed_tools"]
    assert "run_tests" in task["allowed_tools"]
    assert (run_dir / "task_plan_revisions.jsonl").exists()
