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
    assert task["task_kind"] == "implementation"
    assert task["completion_contract"]["requires_changed_artifact"] is True
    assert task["verification_policy"]["required"] is True
    assert "restore_backup" in task["allowed_tools"]
    assert "Quality:" in task["notes"]


def test_requirement_planner_groups_single_concrete_file_goal() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": "Create hello_runtime.txt containing real model smoke ok",
        "normalized_goal": "Create hello_runtime.txt containing real model smoke ok",
        "target_outputs": ["hello_runtime.txt"],
        "definition_of_done": ["hello_runtime.txt exists", "content is exact"],
        "verification_strategy": ["read file"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create hello_runtime.txt",
                "acceptance": ["file exists"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Write exact content",
                "acceptance": ["content matches"],
            },
            {
                "id": "req-0003",
                "priority": "must",
                "description": "Verify content",
                "acceptance": ["readback matches"],
            },
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)

    assert len(task_plan["tasks"]) == 1
    task = task_plan["tasks"][0]
    assert task["expected_artifacts"] == ["hello_runtime.txt"]
    assert task["task_kind"] == "implementation"
    assert task["expected_changed_files"] == ["hello_runtime.txt"]
    assert "one concrete file" in task["notes"]
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
    assert task["task_kind"] == "implementation"
    assert "completion_contract" in task
    assert task["quality"]["passed"]
    assert "Refined for task quality" in task["notes"]


def test_requirement_planner_groups_single_file_tool_into_one_slice() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": "Create a single-file Python CLI named password_strength.py",
        "normalized_goal": "Develop a single-file Python CLI password strength checker",
        "constraints": ["Must be a single Python file named password_strength.py"],
        "target_outputs": ["Single-file Python CLI tool"],
        "definition_of_done": ["python password_strength.py password prints weak"],
        "verification_strategy": ["execute CLI examples"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Accept a password argument",
                "acceptance": ["Tool accepts password as a positional argument"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Classify weak passwords",
                "acceptance": ["Common passwords return weak"],
            },
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)

    assert len(task_plan["tasks"]) == 1
    task = task_plan["tasks"][0]
    assert task["expected_artifacts"] == ["password_strength.py"]
    assert task["completion_contract"]["requires_changed_artifact"] is True
    assert "Accept a password argument" in task["description"]
    assert "Common passwords return weak" in task["acceptance"]
    assert "single-file tool" in task["notes"]


def test_requirement_planner_marks_diagnostic_tasks() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Fix failing tests",
        "target_outputs": ["tests"],
        "definition_of_done": ["pytest passes"],
        "verification_strategy": ["python -m pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Run pytest to identify failing tests",
                "acceptance": ["failures reported"],
            }
        ],
    }

    task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]

    assert task["task_kind"] == "diagnostic"
    assert task["completion_contract"]["allows_expected_failure"] is True
    assert task["completion_contract"]["requires_changed_artifact"] is False


def test_requirement_planner_splits_oversized_requirement_by_acceptance() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Build a practical password testing tool",
        "target_outputs": ["local_cli"],
        "definition_of_done": ["usable CLI"],
        "verification_strategy": ["unit_tests"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Implement password analysis features",
                "acceptance": [
                    "Detect short passwords",
                    "Detect common passwords",
                    "Detect repeated characters",
                    "Detect missing digits",
                    "Detect missing symbols",
                    "Return a readable score",
                    "Print CLI guidance",
                ],
            }
        ],
    }

    tasks = RequirementPlanner().build_task_plan(goal_spec)["tasks"]

    assert len(tasks) == 3
    assert [len(task["acceptance"]) for task in tasks] == [3, 3, 1]
    assert tasks[0]["status"] == "ready"
    assert tasks[1]["depends_on"] == ["task-0001"]
    assert "Split from req-0001" in tasks[0]["notes"]


def test_requirement_planner_splits_oversized_requirement_by_artifact() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Create a small tool package",
        "target_outputs": ["python_module"],
        "definition_of_done": ["package exists"],
        "verification_strategy": ["unit_tests"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create package files",
                "acceptance": ["CLI exists", "Library exists", "Tests exist", "Docs exist"],
                "expected_artifacts": ["tool.py", "library.py", "tests/test_tool.py", "README.md"],
            }
        ],
    }

    tasks = RequirementPlanner().build_task_plan(goal_spec)["tasks"]

    assert len(tasks) == 4
    assert [task["expected_artifacts"] for task in tasks] == [
        ["tool.py"],
        ["library.py"],
        ["tests/test_tool.py"],
        ["README.md"],
    ]
    assert tasks[0]["expected_changed_files"] == ["tool.py"]
    assert "Split from req-0001" in tasks[0]["notes"]


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
