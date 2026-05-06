from __future__ import annotations

from agent_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator


def test_task_plan_evaluator_passes_well_formed_plan() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "expanded_requirements": [
            {"id": "req-0001", "priority": "must"},
            {"id": "req-0002", "priority": "should"},
        ],
    }
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [
            {
                "task_id": "task-0001",
                "title": "Implement CLI parser",
                "description": "Implement a command line parser for the password tool.",
                "status": "ready",
                "depends_on": [],
                "acceptance": ["Command prints password score"],
                "expected_artifacts": ["password_tool.py"],
                "allowed_tools": ["apply_patch", "run_tests"],
                "task_kind": "implementation",
                "verification_policy": {"required": True},
            },
            {
                "task_id": "task-0002",
                "title": "Add usage documentation",
                "description": "Document local-only behavior and example CLI usage.",
                "status": "backlog",
                "depends_on": ["task-0001"],
                "acceptance": ["README.md contains usage examples"],
                "expected_artifacts": ["README.md"],
                "allowed_tools": ["apply_patch", "run_tests"],
                "task_kind": "report",
                "verification_policy": {"required": False},
            },
        ],
    }

    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, run_id="run-1")

    assert report["status"] == "pass"
    assert report["overall_score"] == 1.0
    assert report["issues"] == []
    assert report["task_count"] == 2


def test_task_plan_evaluator_fails_unverifiable_plan() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "expanded_requirements": [
            {"id": "req-0001", "priority": "must"},
            {"id": "req-0002", "priority": "must"},
            {"id": "req-0003", "priority": "must"},
        ],
    }
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [
            {
                "task_id": "task-0001",
                "title": "Do",
                "description": "Improve",
                "status": "backlog",
                "depends_on": ["task-9999"],
                "acceptance": [],
                "expected_artifacts": [],
                "allowed_tools": ["read_file"],
                "task_kind": "implementation",
                "verification_policy": {"required": True},
            }
        ],
    }

    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, run_id="run-1")
    codes = {issue["code"] for issue in report["issues"]}

    assert report["status"] == "fail"
    assert report["overall_score"] < 0.75
    assert {
        "no_ready_task",
        "missing_dependency",
        "vague_description",
        "missing_acceptance",
        "missing_artifact",
        "missing_write_tool",
    }.issubset(codes)
    assert report["recommendations"]
