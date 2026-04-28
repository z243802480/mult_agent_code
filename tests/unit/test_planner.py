from agent_runtime.agents.planner import FollowUpTaskPlanner


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
