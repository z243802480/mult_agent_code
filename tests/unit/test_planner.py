from agent_runtime.agents.planner import FollowUpTaskPlanner, RequirementPlanner


def test_requirement_planner_adds_expected_artifacts_and_quality_notes() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Create a local CLI notes tool",
        "target_outputs": ["local_cli", "readme", "tests"],
        "definition_of_done": ["CLI works"],
        "verification_strategy": ["unit_tests"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create a notes command line module",
                "acceptance": ["Module exists", "Unit test passes"],
            }
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)
    task = task_plan["tasks"][0]

    assert task["expected_artifacts"]
    assert "src/" in task["expected_artifacts"]
    assert "tests/" in task["expected_artifacts"]
    assert "README.md" in task["expected_artifacts"]
    assert "restore_backup" in task["allowed_tools"]
    assert "Quality:" in task["notes"]
    assert task["quality"]["passed"]


def test_requirement_planner_refines_low_quality_requirements() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Create a password testing tool",
        "target_outputs": ["local_cli"],
        "definition_of_done": ["Tool is usable"],
        "verification_strategy": ["unit_tests"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Improve",
                "acceptance": [],
            }
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)
    task = task_plan["tasks"][0]

    assert "Create a password testing tool" in task["description"]
    assert task["acceptance"]
    assert task["expected_artifacts"]
    assert task["quality"]["passed"]
    assert "Refined for task quality" in task["notes"]


def test_follow_up_planner_skips_duplicate_tasks() -> None:
    existing_tasks = [
        {
            "task_id": "task-0001",
            "title": "Create README helper",
            "description": "Create README helper artifact",
            "status": "done",
        }
    ]
    eval_report = {
        "run_id": "run-1",
        "outcome_eval": {
            "follow_up_tasks": [
                {
                    "title": "Create README helper",
                    "description": "Create README helper artifact",
                }
            ]
        },
        "trajectory_eval": {},
    }

    tasks = FollowUpTaskPlanner().build_follow_up_tasks(eval_report, existing_tasks)

    assert tasks == []


def test_follow_up_planner_chains_new_tasks_after_existing_work() -> None:
    existing_tasks = [
        {
            "task_id": "task-0001",
            "title": "Build core",
            "description": "Build core module",
            "status": "done",
        }
    ]
    eval_report = {
        "run_id": "run-1",
        "outcome_eval": {
            "follow_up_tasks": [
                {
                    "title": "Add report",
                    "description": "Add final report artifact",
                    "acceptance": ["Report exists"],
                },
                {
                    "title": "Add docs",
                    "description": "Add user docs",
                },
            ]
        },
        "trajectory_eval": {},
    }

    tasks = FollowUpTaskPlanner().build_follow_up_tasks(eval_report, existing_tasks)

    assert [task["task_id"] for task in tasks] == ["task-0002", "task-0003"]
    assert tasks[0]["depends_on"] == ["task-0001"]
    assert tasks[1]["depends_on"] == ["task-0002"]
