from __future__ import annotations

from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator


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


# --- profile-aware lint (reaudit #8 phase B): a unified task is design intent, not a smell ----

def _unified_plan() -> tuple[dict, dict]:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "expanded_requirements": [
            {"id": f"req-{i:04d}", "priority": "must"} for i in range(1, 5)
        ],
    }
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [
            {
                "task_id": "task-0001",
                "title": "Implement the whole slice",
                "description": "One deliberate session_agent slice covering all must requirements.",
                "status": "ready",
                "depends_on": [],
                # 6 acceptance criteria: thorough spec, deliberately not split.
                "acceptance": [
                    "Command prints password score",
                    "Report contains the score table",
                    "CLI returns exit code 0",
                    "Output matches the golden sample",
                    "Tests pass on the fixture project",
                    "File exists at password_tool.py",
                ],
                "expected_artifacts": ["password_tool.py"],
                "allowed_tools": ["apply_patch", "run_tests"],
                "task_kind": "implementation",
                "verification_policy": {"required": True},
            }
        ],
    }
    return task_plan, goal_spec


def test_session_agent_unified_task_is_not_flagged_under_decomposed_or_oversized() -> None:
    # The dogfood 0.98+"需留意" contradiction: a DELIBERATE single-slice session_agent plan was
    # scored down for "should split" / "too many acceptance criteria". The profile is part of the
    # judgement now.
    task_plan, goal_spec = _unified_plan()
    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, execution_profile="session_agent")
    codes = {issue.code for issue in []} | set()
    assert report["status"] == "pass", report["issues"]
    codes = {item["code"] for item in report["issues"]}
    assert "under_decomposed_plan" not in codes
    assert "oversized_acceptance" not in codes


def test_harness_profile_still_flags_the_same_shape() -> None:
    # The multi-task ideal keeps its teeth outside session_agent — legacy behaviour unchanged.
    task_plan, goal_spec = _unified_plan()
    # NB: oversized_acceptance carries a legacy hard-coded exemption for task-0001; use a later id
    # so the harness-profile assertion exercises the real check (cleanup candidate for phase A).
    task_plan["tasks"][0]["task_id"] = "task-0009"
    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, execution_profile="harness")
    codes = {item["code"] for item in report["issues"]}
    assert "under_decomposed_plan" in codes
    assert "oversized_acceptance" in codes
    assert report["status"] == "warn"
