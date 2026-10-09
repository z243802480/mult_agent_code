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
    # The multi-task ideal keeps its teeth outside session_agent — under_decomposed still
    # fires for a single-deliberate-slice plan judged as harness.
    task_plan, goal_spec = _unified_plan()
    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, execution_profile="harness")
    codes = {item["code"] for item in report["issues"]}
    assert "under_decomposed_plan" in codes
    assert report["status"] == "warn"


def test_single_task_plan_is_oversized_exempt_regardless_of_task_id() -> None:
    # ADR-0033 cleanup: the legacy hard-coded task-0001 exemption is now the semantic
    # "a single-task plan has nothing to split into" — any id, any profile.
    task_plan, goal_spec = _unified_plan()
    task_plan["tasks"][0]["task_id"] = "task-0009"
    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, execution_profile="harness")
    codes = {item["code"] for item in report["issues"]}
    assert "oversized_acceptance" not in codes


def test_multi_task_plan_still_flags_oversized_acceptance_on_any_task() -> None:
    # With more than one task there IS something to split into, so >4 acceptance on a
    # slice is a real decomposition smell — and no task id is exempt any more.
    task_plan, goal_spec = _unified_plan()
    filler = dict(task_plan["tasks"][0])
    filler.update(
        {
            "task_id": "task-0002",
            "title": "Write the user guide",
            "description": "Document the tool usage, options, and examples.",
            "acceptance": ["Guide exists", "Guide covers options"],
            "depends_on": ["task-0001"],
            "status": "backlog",
        }
    )
    task_plan["tasks"].append(filler)
    report = TaskPlanEvaluator().evaluate(task_plan, goal_spec, execution_profile="harness")
    codes = {item["code"] for item in report["issues"]}
    assert "oversized_acceptance" in codes
