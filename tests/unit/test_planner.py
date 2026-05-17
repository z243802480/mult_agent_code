from asteria_runtime.agents.planner import FollowUpTaskPlanner, RequirementPlanner


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
    assert "src/notes_tool.py" in task["read_scope"]
    assert "src/notes_tool.py" in task["write_scope"]
    assert "tests/test_notes_tool.py" in task["write_scope"]
    assert task["parallel_safety"] == "serial"
    assert task["failure_policy"] == "create_repair_task"
    assert task["context_requirements"]["mount_type"] == "coding_context"
    assert "list_files" in task["allowed_tools"]
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


def test_requirement_planner_infers_answer_module_contract() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Create a complete module",
        "target_outputs": ["python_module"],
        "definition_of_done": ["answer() returns 42"],
        "verification_strategy": ["python command"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create a module exposing answer()",
                "acceptance": ["answer() returns 42"],
            }
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)
    task = task_plan["tasks"][0]

    assert task["expected_changed_files"] == ["complete_module.py"]
    assert task["write_scope"] == ["complete_module.py"]
    assert "complete_module.py" in task["read_scope"]


def test_requirement_planner_requires_runtime_request_for_broad_write_scope() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Improve the application",
        "target_outputs": ["python_module"],
        "definition_of_done": ["implementation is improved"],
        "verification_strategy": ["pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Improve the application behavior",
                "acceptance": ["behavior is improved"],
            }
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)
    task = task_plan["tasks"][0]

    assert task["expected_artifacts"] == ["src/"]
    assert task["expected_changed_files"] == []
    assert task["write_scope"] == []
    assert task["parallel_safety"] == "serial"
    assert "runtime scope request" in task["notes"]


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


def test_requirement_planner_groups_atomic_multifile_cli_artifacts() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": (
            "Create a small multi-file Python notes CLI. Use a package directory named "
            "notes_app with storage.py and cli.py, plus a runnable notes.py entrypoint. "
            'It must support `python notes.py add "ship gray"` and `python notes.py list`, '
            "storing notes in notes.json under the current directory."
        ),
        "normalized_goal": "Create a multi-file Python notes CLI",
        "target_outputs": ["local_cli", "python_module"],
        "definition_of_done": [
            'python notes.py add "ship gray" exits successfully',
            "python notes.py list prints ship gray",
            "notes are stored in notes.json",
        ],
        "verification_strategy": [
            'python notes.py add "ship gray"',
            "python notes.py list",
        ],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create notes_app storage and CLI modules",
                "acceptance": ["storage.py and cli.py exist"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Create notes.py entrypoint and notes.json storage behavior",
                "acceptance": ["notes.py delegates to notes_app", "notes.json stores notes"],
            },
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)

    assert len(task_plan["tasks"]) == 1
    task = task_plan["tasks"][0]
    assert task["expected_artifacts"] == [
        "notes_app/storage.py",
        "notes_app/cli.py",
        "notes.py",
        "notes.json",
        "notes_app/__init__.py",
    ]
    assert task["expected_changed_files"] == [
        "notes_app/storage.py",
        "notes_app/cli.py",
        "notes.py",
        "notes_app/__init__.py",
    ]
    assert "notes.json" not in task["write_scope"]
    assert "Runtime commands create or update notes.json as specified" in task["acceptance"]
    assert "`python notes.py list` exits successfully" in task["acceptance"]
    assert "complete multi-file tool slice" in task["notes"]


def test_requirement_planner_groups_targeted_failing_test_repair() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": (
            "Fix the failing tests in this project. Run the Python tests, identify the bug "
            "in buggy_math.py, and make the tests pass with the smallest reasonable change."
        ),
        "normalized_goal": "Fix failing tests by repairing buggy_math.py",
        "target_outputs": ["buggy_math.py"],
        "definition_of_done": ["pytest passes", "buggy_math.py contains the minimal fix"],
        "verification_strategy": ["pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Run tests and inspect buggy_math.py",
                "acceptance": ["failing assertion is understood"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Apply the smallest fix in buggy_math.py",
                "acceptance": ["tests pass after the change"],
            },
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)

    assert len(task_plan["tasks"]) == 1
    task = task_plan["tasks"][0]
    assert task["expected_artifacts"] == ["buggy_math.py"]
    assert task["expected_changed_files"] == ["buggy_math.py"]
    assert task["write_scope"] == ["buggy_math.py"]
    assert "pytest passes" in task["acceptance"]
    assert "targeted repair slice" in task["notes"]


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
    assert task["write_scope"] == []
    assert task["parallel_safety"] == "readonly"
    assert "write_file" not in task["allowed_tools"]
    assert "apply_patch" not in task["allowed_tools"]
    assert task["context_requirements"]["mount_type"] == "debug_context"


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


def test_requirement_planner_adds_multi_agent_strategy_for_disjoint_artifacts() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "normalized_goal": "Create independent documentation artifacts",
        "target_outputs": ["docs/a.md", "docs/b.md", "docs/c.md"],
        "definition_of_done": ["docs exist"],
        "verification_strategy": [],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create independent docs/a.md docs/b.md docs/c.md files.",
                "acceptance": ["a exists", "b exists", "c exists"],
                "expected_artifacts": ["docs/a.md", "docs/b.md", "docs/c.md"],
            }
        ],
    }

    tasks = RequirementPlanner().build_task_plan(goal_spec)["tasks"]

    assert len(tasks) == 1
    assert tasks[0]["parallel_safety"] == "disjoint_writes"
    assert tasks[0]["multi_agent_strategy"]["mode"] == "disjoint_write_workers"
    assert tasks[0]["multi_agent_strategy"]["max_child_workers"] == 3
    assert "Multi-agent strategy: disjoint_write_workers" in tasks[0]["notes"]


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


def test_planner_notes_include_capability_feedback_hint() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-feedback",
        "original_goal": "Create feedback.txt",
        "normalized_goal": "Create feedback.txt",
        "goal_type": "software_tool",
        "assumptions": [],
        "constraints": [],
        "non_goals": [],
        "expanded_requirements": [
            {
                "id": "req-feedback",
                "priority": "must",
                "description": "Create feedback.txt with one line.",
                "acceptance": ["feedback.txt exists"],
                "expected_artifacts": ["feedback.txt"],
            }
        ],
        "target_outputs": ["feedback.txt"],
        "definition_of_done": ["feedback.txt exists"],
        "verification_strategy": [],
        "budget": {},
    }
    runtime_context = {
        "capability_feedback": [
            {"message": "prefer narrower read/write scope before scaling similar tasks"}
        ]
    }

    task = RequirementPlanner().build_task_plan(goal_spec, runtime_context)["tasks"][0]

    assert "capability feedback: prefer narrower read/write scope" in task["notes"]
