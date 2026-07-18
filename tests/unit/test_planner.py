from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.commands.plan_command import _apply_validation_probe_hints
from asteria_runtime.core.execution_profile import SESSION_AGENT


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


def test_requirement_planner_propagates_explicit_execution_preferences() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": "Delegate the review to a subagent and inspect input/.",
        "normalized_goal": "Review input documents",
        "target_outputs": ["reports/review.md"],
        "definition_of_done": ["Review exists"],
        "verification_strategy": ["Verify report exists"],
        "execution_preferences": {
            "delegation": "required",
            "requested_capability": "subagent",
            "requested_read_scope": ["input/"],
        },
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create reports/review.md",
                "acceptance": ["Report exists"],
            }
        ],
    }

    task = RequirementPlanner().build_task_plan(
        goal_spec,
        execution_profile=SESSION_AGENT,
    )["tasks"][0]

    assert task["execution_preferences"]["delegation"] == "required"
    assert "input/" in task["read_scope"]
    assert "reports/review.md" in task["read_scope"]


def test_validation_probe_hint_forces_readonly_fanout_strategy() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "serial",
                "write_scope": ["probe.txt"],
                "expected_changed_files": ["probe.txt"],
                "expected_artifacts": ["probe.txt"],
                "allowed_tools": ["write_file", "run_command"],
                "acceptance": ["probe artifact exists"],
            },
            {
                "task_id": "task-0002",
                "task_kind": "implementation",
            },
        ]
    }

    _apply_validation_probe_hints(task_plan, ["readonly_fanout_succeeds"])

    task = task_plan["tasks"][0]
    assert len(task_plan["tasks"]) == 1
    assert task["runtime_profile_hints"]["force_next_action"] == "subagent"
    assert task["runtime_profile_hints"]["validation_probe_ids"] == ["readonly_fanout_succeeds"]
    assert task["parallel_safety"] == "readonly"
    assert task["write_scope"] == []
    assert task["expected_changed_files"] == []
    assert task["multi_agent_strategy"]["mode"] == "readonly_fanout"
    assert task["multi_agent_strategy"]["max_child_workers"] == 2


def test_validation_probe_hint_expands_read_scope_for_readonly_write_gate() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "serial",
                "write_scope": ["probe.txt"],
                "expected_changed_files": ["probe.txt"],
                "expected_artifacts": ["probe.txt"],
                "allowed_tools": ["write_file", "run_command"],
                "acceptance": ["probe artifact exists"],
            }
        ]
    }

    _apply_validation_probe_hints(task_plan, ["readonly_write_tool_blocked"])

    task = task_plan["tasks"][0]
    assert task["runtime_profile_hints"]["force_next_action"] == "subagent"
    assert task["runtime_profile_hints"]["validation_probe_ids"] == ["readonly_write_tool_blocked"]
    assert task["parallel_safety"] == "readonly"
    assert task["write_scope"] == []
    assert "readonly_write_gate_probe.txt" in task["read_scope"]


def test_validation_probe_hint_scopes_repair_replan_probe_to_benchmark() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "disjoint_writes",
                "read_scope": ["tests/"],
                "write_scope": ["probe.txt"],
                "expected_changed_files": ["probe.txt"],
                "expected_artifacts": ["probe.txt"],
                "allowed_tools": ["write_file", "run_command"],
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            }
        ]
    }

    _apply_validation_probe_hints(task_plan, ["repair_replan_path"])

    task = task_plan["tasks"][0]
    assert task["task_kind"] == "diagnostic"
    assert task["parallel_safety"] == "serial"
    assert task["read_scope"] == ["AGENTS.md", "benchmarks/failing_tests_project"]
    assert task["write_scope"] == []
    assert task["expected_changed_files"] == []
    assert task["allowed_tools"] == ["run_command"]
    assert task["completion_contract"]["allows_expected_failure"] is False
    assert "multi_agent_strategy" not in task


def test_validation_probe_hint_scopes_ask_stop_probe_to_decision_boundary() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "disjoint_writes",
                "read_scope": ["benchmarks"],
                "write_scope": ["probe.txt"],
                "expected_changed_files": ["probe.txt"],
                "expected_artifacts": ["probe.txt"],
                "allowed_tools": ["write_file", "run_command"],
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            }
        ]
    }

    _apply_validation_probe_hints(task_plan, ["ask_stop_path"])

    task = task_plan["tasks"][0]
    assert task["task_kind"] == "diagnostic"
    assert task["parallel_safety"] == "serial"
    assert task["read_scope"] == ["AGENTS.md"]
    assert task["write_scope"] == []
    assert task["expected_changed_files"] == []
    assert task["expected_artifacts"] == []
    assert task["completion_contract"]["requires_changed_artifact"] is False
    assert task["completion_contract"]["allows_expected_failure"] is True
    assert "multi_agent_strategy" not in task


def test_validation_probe_hint_scopes_context_pressure_probe_to_diagnostic() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "disjoint_writes",
                "read_scope": ["benchmarks"],
                "write_scope": ["probe.txt"],
                "expected_changed_files": ["probe.txt"],
                "expected_artifacts": ["probe.txt"],
                "allowed_tools": ["write_file", "run_command"],
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            }
        ]
    }

    _apply_validation_probe_hints(task_plan, ["context_pressure_path"])

    task = task_plan["tasks"][0]
    assert task["task_kind"] == "diagnostic"
    assert task["parallel_safety"] == "serial"
    assert task["read_scope"] == ["AGENTS.md", "docs/zh/当前状态与路线.md"]
    assert task["write_scope"] == []
    assert task["expected_changed_files"] == []
    assert task["completion_contract"]["requires_changed_artifact"] is False
    assert task["completion_contract"]["allows_expected_failure"] is True
    assert "multi_agent_strategy" not in task


def test_validation_probe_hint_scopes_capability_selection_probe_to_diagnostic() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "parallel_safety": "disjoint_writes",
                "read_scope": ["benchmarks"],
                "write_scope": ["capability_decisions.jsonl"],
                "expected_changed_files": ["capability_decisions.jsonl"],
                "expected_artifacts": ["capability_decisions.jsonl"],
                "allowed_tools": ["write_file", "run_command"],
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            }
        ]
    }

    _apply_validation_probe_hints(task_plan, ["capability_selection_path"])

    task = task_plan["tasks"][0]
    assert task["task_kind"] == "diagnostic"
    assert task["parallel_safety"] == "serial"
    assert task["read_scope"] == ["AGENTS.md", "docs/zh/运行命令.md"]
    assert task["write_scope"] == []
    assert task["expected_changed_files"] == []
    assert task["expected_artifacts"] == []
    assert task["completion_contract"]["requires_changed_artifact"] is False
    assert task["completion_contract"]["allows_expected_failure"] is True
    assert "multi_agent_strategy" not in task


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


def test_requirement_planner_prefers_existing_artifact_scope_from_context() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-existing",
        "normalized_goal": "Improve calculator behavior",
        "target_outputs": ["python_module"],
        "definition_of_done": ["calculator handles subtraction", "unit tests pass"],
        "verification_strategy": ["pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Update calculator behavior and its unit test.",
                "acceptance": ["calculator handles subtraction", "unit test passes"],
            }
        ],
    }
    runtime_context = {
        "workspace_files": [
            {"path": "src/calculator.py"},
            {"path": "tests/test_calculator.py"},
            {"path": "src/unrelated.py"},
        ]
    }

    task = RequirementPlanner().build_task_plan(goal_spec, runtime_context)["tasks"][0]

    assert task["expected_artifacts"] == [
        "src/calculator.py",
        "tests/test_calculator.py",
    ]
    assert task["expected_changed_files"] == [
        "src/calculator.py",
        "tests/test_calculator.py",
    ]
    assert task["write_scope"] == [
        "src/calculator.py",
        "tests/test_calculator.py",
    ]
    assert "src/" not in task["write_scope"]
    assert "tests/" not in task["write_scope"]


def test_requirement_planner_does_not_treat_fixture_mentions_as_write_scope() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-kb",
        "normalized_goal": "Build a local markdown knowledge base search tool",
        "target_outputs": ["python_module"],
        "definition_of_done": ["search returns fixture file"],
        "verification_strategy": ["python markdown_kb.py notes runtime"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Index local markdown files and search by keyword",
                "acceptance": [
                    "markdown_kb.py accepts a directory and keyword",
                    "kb_index.json includes fixture markdown files",
                    "searching for runtime returns asteria_runtime.md",
                ],
            }
        ],
    }
    runtime_context = {
        "workspace_files": [
            {"path": "notes/asteria_runtime.md"},
            {"path": "notes/security.md"},
        ]
    }

    task = RequirementPlanner().build_task_plan(goal_spec, runtime_context)["tasks"][0]

    assert "notes/asteria_runtime.md" not in task["write_scope"]
    assert "notes/security.md" not in task["write_scope"]
    assert "markdown_kb.py" in task["expected_changed_files"]
    assert "kb_index.json" in task["expected_changed_files"]
    assert "notes/asteria_runtime.md" not in task["expected_changed_files"]


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
    assert "worker_transport" not in task.get("runtime_profile_hints", {})


def test_requirement_planner_groups_atomic_multifile_cli_artifacts() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": (
            "Create a small multi-file Python notes CLI. Use a package directory named "
            "notes_app with storage.py and cli.py, plus a runnable notes.py entrypoint. "
            'It must support `python notes.py add "ship validation"` and `python notes.py list`, '
            "storing notes in notes.json under the current directory."
        ),
        "normalized_goal": "Create a multi-file Python notes CLI",
        "target_outputs": ["local_cli", "python_module"],
        "definition_of_done": [
            'python notes.py add "ship validation" exits successfully',
            "python notes.py list prints ship validation",
            "notes are stored in notes.json",
        ],
        "verification_strategy": [
            'python notes.py add "ship validation"',
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


def test_atomic_multifile_title_reflects_goal_not_generic_template() -> None:
    # dogfood friction #4: the atomic multi-file branch hardcoded "Implement complete multi-file CLI
    # artifact set" for every goal — the main thread showed a title unrelated to the ask. The title
    # must now name the actual goal.
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": (
            "Create a small multi-file Python notes CLI. Use a package directory named "
            "notes_app with storage.py and cli.py, plus a runnable notes.py entrypoint. "
            'It must support `python notes.py add "ship validation"` and `python notes.py list`, '
            "storing notes in notes.json under the current directory."
        ),
        "normalized_goal": "Create a multi-file Python notes CLI",
        "target_outputs": ["local_cli", "python_module"],
        "definition_of_done": [
            'python notes.py add "ship validation" exits successfully',
            "python notes.py list prints ship validation",
            "notes are stored in notes.json",
        ],
        "verification_strategy": [
            'python notes.py add "ship validation"',
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

    task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]

    # Atomic multi-file branch (single grouped task) with a goal-derived title.
    assert task["notes"].__contains__("complete multi-file tool slice")
    assert task["title"] == "Create a multi-file Python notes CLI"
    assert task["title"] != "Implement complete multi-file CLI artifact set"


def test_planner_widens_write_scope_when_goal_requests_test_authoring() -> None:
    # dogfood friction #4: a goal that asks for unit tests but names no test file used to scope only
    # the source files, so the doer's test write landed outside write_scope and was denied. Test
    # authoring must be ALLOWED (write_scope) without becoming REQUIRED (expected_changed_files).
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": (
            "Create a small multi-file Python notes CLI with a package directory named notes_app "
            "containing storage.py and cli.py, plus a runnable notes.py entrypoint. Add unit tests "
            "for the CLI behavior."
        ),
        "normalized_goal": "Create a multi-file Python notes CLI with unit tests",
        "target_outputs": ["local_cli", "python_module"],
        "definition_of_done": ["python notes.py list works", "unit tests cover the CLI"],
        "verification_strategy": ["python notes.py list"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Create notes_app storage.py and cli.py plus notes.py entrypoint",
                "acceptance": ["storage.py and cli.py exist"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Add unit tests covering the CLI behavior",
                "acceptance": ["unit tests exist and pass"],
            },
        ],
    }

    task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]

    # The doer may now author a test anywhere under tests/ ...
    assert "tests/" in task["write_scope"]
    # ... but tests are not forced: the completion contract still keys off the source deliverable.
    assert not any(
        str(path).startswith("tests/") or "test_" in str(path)
        for path in task["expected_changed_files"]
    )


def test_planner_does_not_widen_scope_for_repair_or_forbidding_goal() -> None:
    # The scope-widening must never fire for a targeted repair (verifies against a pre-existing test —
    # widening would let the model edit the very test it is graded against) or a goal that explicitly
    # forbids touching tests.
    planner = RequirementPlanner()
    repair_goal = {
        "schema_version": "0.1.0",
        "goal_id": "goal-repair",
        "original_goal": "Fix the failing unit tests by repairing buggy_math.py and make them pass.",
        "normalized_goal": "Fix failing tests by repairing buggy_math.py",
        "target_outputs": ["buggy_math.py"],
        "definition_of_done": ["pytest passes"],
        "verification_strategy": ["pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Repair buggy_math.py so the unit tests pass",
                "acceptance": ["tests pass"],
            }
        ],
    }
    assert planner._wants_test_authoring(repair_goal) is False

    forbid_goal = {
        "schema_version": "0.1.0",
        "goal_id": "goal-forbid",
        "normalized_goal": "Add a checker with unit tests",
        "original_goal": "Add a checker module and unit tests, but do not modify the test harness.",
        "target_outputs": ["checker.py"],
        "definition_of_done": ["checker works"],
        "verification_strategy": ["pytest"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Implement checker.py. Do not modify test files.",
                "acceptance": ["No test files were modified."],
            }
        ],
    }
    assert planner._wants_test_authoring(forbid_goal) is False


def test_requirement_planner_keeps_docs_readme_directory_target() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-doc-readme",
        "normalized_goal": "Create documentation README",
        "target_outputs": ["README.md"],
        "definition_of_done": ["docs/README.md exists"],
        "verification_strategy": ["file check"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": (
                    "Create a README.md in the docs/ directory with Overview, Quick Start, "
                    "and License sections."
                ),
                "acceptance": ["docs/README.md is valid Markdown"],
            }
        ],
    }

    task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]

    assert task["expected_artifacts"] == ["docs/README.md"]
    assert task["expected_changed_files"] == ["docs/README.md"]
    assert task["write_scope"] == ["docs/README.md"]


def test_requirement_planner_excludes_tests_when_goal_forbids_test_modification() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-debug-repair",
        "normalized_goal": "Fix failing tests by repairing buggy_math.py",
        "target_outputs": ["buggy_math.py", "test_buggy_math.py"],
        "definition_of_done": ["pytest passes"],
        "verification_strategy": ["pytest", "diff_workspace"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": (
                    "Fix the failing tests in this project by changing buggy_math.py. "
                    "No other files are modified."
                ),
                "acceptance": [
                    "The add function in buggy_math.py returns a + b.",
                    "No test files were modified, including test_buggy_math.py.",
                ],
            }
        ],
    }

    task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]

    assert task["expected_changed_files"] == ["buggy_math.py"]
    assert task["write_scope"] == ["buggy_math.py"]
    assert "test_buggy_math.py" in task["read_scope"]
    assert "diff_workspace" in task["allowed_tools"]


def test_requirement_planner_groups_named_single_file_bugfix_with_test_context() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-calc-fix",
        "original_goal": (
            "Fix calc.py so add(2, 3) returns 5. Keep the change limited to calc.py "
            "and preserve the existing test intent."
        ),
        "normalized_goal": "Fix calc.py add behavior",
        "target_outputs": ["calc.py", "test_calc.py"],
        "definition_of_done": ["add(2, 3) returns 5", "pytest test_calc.py passes"],
        "verification_strategy": ["pytest test_calc.py"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Change calc.py so add uses addition",
                "acceptance": ["add(2, 3) returns 5"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Ensure existing test in test_calc.py passes",
                "acceptance": ["pytest test_calc.py passes"],
            },
            {
                "id": "req-0003",
                "priority": "must",
                "description": "Keep the fix contained to calc.py only",
                "acceptance": ["No modifications to test_calc.py"],
            },
        ],
    }

    task_plan = RequirementPlanner().build_task_plan(goal_spec)

    assert len(task_plan["tasks"]) == 1
    task = task_plan["tasks"][0]
    assert task["expected_artifacts"] == ["calc.py", "test_calc.py"]
    assert task["expected_changed_files"] == ["calc.py"]
    assert task["write_scope"] == ["calc.py"]
    assert "test_calc.py" in task["read_scope"]
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

    tasks = RequirementPlanner().build_task_plan(goal_spec, execution_profile="harness")["tasks"]

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

    tasks = RequirementPlanner().build_task_plan(goal_spec, execution_profile="harness")["tasks"]

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


def test_session_agent_unified_task_collapses_beta_coding_goal() -> None:
    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-0001",
        "original_goal": "给一个小 CLI 增加 --version 参数，并补一个测试。",
        "normalized_goal": "给一个小 CLI 增加 --version 参数，并补一个测试。",
        "target_outputs": ["local_cli"],
        "definition_of_done": ["--version 可用", "pytest 通过"],
        "verification_strategy": ["pytest -q"],
        "expanded_requirements": [
            {
                "id": "req-0001",
                "priority": "must",
                "description": "Add --version flag to CLI",
                "acceptance": ["--version prints version"],
            },
            {
                "id": "req-0002",
                "priority": "must",
                "description": "Add pytest coverage",
                "acceptance": ["pytest passes"],
            },
        ],
    }

    tasks = RequirementPlanner().build_task_plan(goal_spec, execution_profile=SESSION_AGENT)[
        "tasks"
    ]
    assert tasks[0]["execution_profile"] == "session_agent"
    assert tasks[0]["task_kind"] == "implementation"
    assert "apply_patch" in tasks[0]["allowed_tools"]
    assert "--version prints version" in tasks[0]["acceptance"]
    assert "pytest passes" in tasks[0]["acceptance"]


def test_task_kind_stays_implementation_when_description_mentions_verify() -> None:
    requirement = {
        "description": (
            "Add a --version flag to greet_cli.py\n"
            "- Verify existing greet behavior still works after changes"
        ),
        "acceptance": ["pytest test_greet_cli.py passes"],
    }
    kind = RequirementPlanner()._task_kind(
        requirement,
        ["greet_cli.py", "test_greet_cli.py"],
        {},
    )
    assert kind == "implementation"


def test_prose_target_output_with_embedded_path_is_not_a_file_path() -> None:
    # Dogfood run-20260718 #2: the goal-spec model emitted a prose target_output
    # ("新增测试用例在 tests/test_storage.py") whose BASENAME looks like a file, so the
    # single-file branch adopted the whole sentence as THE artifact — it became write_scope
    # verbatim and denied every real file. Whitespace → prose, same rule as task_contract.
    planner = RequirementPlanner()
    assert planner._looks_like_file_path("tests/test_storage.py") is True
    assert planner._looks_like_file_path("新增测试用例在 tests/test_storage.py") is False
    goal_spec = {
        "target_outputs": [
            "修改后的 Note 模型(含 tags 字段)",
            "新增测试用例在 tests/test_storage.py",
        ],
    }
    assert planner._single_output_file(goal_spec) is None
