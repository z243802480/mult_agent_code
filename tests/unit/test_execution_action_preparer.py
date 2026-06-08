import pytest

from asteria_runtime.core.execution_action_preparer import ExecutionActionPreparer


def _preparer() -> ExecutionActionPreparer:
    def shell_denial(_policy: dict, command: str) -> str | None:
        if "|" in command:
            return "Shell operator is not allowed: |"
        if ">" in command:
            return "Shell operator is not allowed: >"
        return None

    return ExecutionActionPreparer(shell_denial)


def _task(**overrides: object) -> dict:
    task = {
        "task_id": "task-0001",
        "allowed_tools": ["write_file", "run_command"],
        "verification_policy": {
            "required": True,
            "commands": ["Run `python tool.py --help`."],
        },
        "expected_artifacts": ["tool.py"],
        "expected_changed_files": ["tool.py"],
    }
    task.update(overrides)
    return task


def test_preparer_moves_inline_run_command_to_verification() -> None:
    action = {
        "tool_calls": [
            {"tool_name": "write_file", "args": {"path": "tool.py", "content": "print('ok')"}},
            {"tool_name": "run_command", "args": {"command": "python tool.py --help"}},
        ],
        "verification": [],
    }

    prepared = _preparer().prepare(action, _task(), {})

    assert [call["tool_name"] for call in prepared["tool_calls"]] == ["write_file"]
    assert prepared["verification"][0]["args"]["command"] == "python tool.py --help"


def test_preparer_uses_planned_verification_when_required_action_omits_it() -> None:
    action = {
        "tool_calls": [
            {"tool_name": "write_file", "args": {"path": "tool.py", "content": "print('ok')"}},
        ],
        "verification": [],
    }

    prepared = _preparer().prepare(action, _task(), {})

    assert [call["args"]["command"] for call in prepared["verification"]] == [
        "python tool.py --help",
    ]


def test_preparer_replaces_safe_unsafe_verification_with_planned_command() -> None:
    action = {
        "tool_calls": [
            {"tool_name": "write_file", "args": {"path": "tool.py", "content": "print('ok')"}},
        ],
        "verification": [
            {"tool_name": "run_command", "args": {"command": "python tool.py --help | cat"}},
        ],
    }

    prepared = _preparer().prepare(action, _task(), {})

    assert [call["args"]["command"] for call in prepared["verification"]] == [
        "python tool.py --help",
    ]


def test_preparer_replaces_out_of_scope_redirect_with_planned_command() -> None:
    def shell_denial(_policy: dict, command: str) -> str | None:
        if "../../" in command:
            return "Shell output redirect denied: ../../outside.txt"
        return None

    action = {
        "tool_calls": [
            {"tool_name": "write_file", "args": {"path": "tool.py", "content": "print('ok')"}},
        ],
        "verification": [
            {"tool_name": "run_command", "args": {"command": "echo unsafe > ../../outside.txt"}},
        ],
    }

    prepared = ExecutionActionPreparer(shell_denial).prepare(action, _task(), {})

    assert [call["args"]["command"] for call in prepared["verification"]] == [
        "python tool.py --help",
    ]


def test_preparer_replaces_doc_only_verification_with_stable_file_check() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "docs/validation_batch_note.md", "content": "# Validation\n"},
            },
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        'python -c "from pathlib import Path; '
                        'paths=["docs/validation_batch_note.md"]; print(paths)"'
                    )
                },
            },
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            expected_artifacts=["docs/validation_batch_note.md"],
            expected_changed_files=["docs/validation_batch_note.md"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    commands = [call["args"]["command"] for call in prepared["verification"]]
    assert len(commands) == 1
    assert "docs/validation_batch_note.md" in commands[0]
    assert "missing or empty" in commands[0]
    assert "bad" not in commands[0]


def test_preparer_preserves_valid_doc_content_verification() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "CONTEXT.md", "content": "remote\n"},
            },
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        'python -c "from pathlib import Path; '
                        "assert Path('CONTEXT.md').read_text(encoding='utf-8') == 'local\\n'\""
                    )
                },
            },
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            expected_artifacts=["CONTEXT.md"],
            expected_changed_files=["CONTEXT.md"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    commands = [call["args"]["command"] for call in prepared["verification"]]
    assert len(commands) == 1
    assert "read_text" in commands[0]
    assert "missing or empty" not in commands[0]


def test_preparer_drops_redundant_root_list_after_verified_standalone_artifact() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "hello.txt", "content": "hello"},
            },
            {"tool_name": "list_files", "args": {"path": "."}},
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python -c \"from pathlib import Path; assert Path('hello.txt').exists()\""
                },
            }
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            allowed_tools=["write_file", "list_files", "run_command"],
            expected_artifacts=["hello.txt"],
            expected_changed_files=["hello.txt"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    assert [call["tool_name"] for call in prepared["tool_calls"]] == ["write_file"]


def test_preparer_drops_parent_list_before_text_artifact_write() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "docs/hello.txt", "content": "hello"},
            },
            {"tool_name": "list_files", "args": {"path": "docs"}},
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python -c \"from pathlib import Path; assert Path('docs/hello.txt').exists()\""
                },
            }
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            allowed_tools=["write_file", "list_files", "run_command"],
            expected_artifacts=["docs/hello.txt"],
            expected_changed_files=["docs/hello.txt"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    assert [call["tool_name"] for call in prepared["tool_calls"]] == ["write_file"]


def test_preparer_normalizes_structured_apply_patch_replace() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "apply_patch",
                "args": {
                    "patch": [
                        {
                            "path": "calc.py",
                            "operations": [
                                {
                                    "op": "replace",
                                    "old_text": "def add(a, b):\n    return a - b",
                                    "new_text": "def add(a, b):\n    return a + b",
                                }
                            ],
                        }
                    ]
                },
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "python -m py_compile calc.py"},
            }
        ],
    }

    prepared = ExecutionActionPreparer(lambda _policy, _command: None).prepare(
        action,
        _task(
            expected_artifacts=["calc.py"],
            expected_changed_files=["calc.py"],
            allowed_tools=["apply_patch", "run_command"],
            verification_required=True,
        ),
        {},
    )

    patch = prepared["tool_calls"][0]["args"]["patch"]
    assert isinstance(patch, str)
    assert "--- a/calc.py" in patch
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch


def test_preparer_normalizes_apply_patch_path_old_new_args() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "apply_patch",
                "args": {
                    "path": "calc.py",
                    "old_text": "def add(a, b):\n    return a - b",
                    "new_text": "def add(a, b):\n    return a + b",
                },
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "python -m py_compile calc.py"},
            }
        ],
    }

    prepared = ExecutionActionPreparer(lambda _policy, _command: None).prepare(
        action,
        _task(
            expected_artifacts=["calc.py"],
            expected_changed_files=["calc.py"],
            allowed_tools=["apply_patch", "run_command"],
            verification_required=True,
        ),
        {},
    )

    args = prepared["tool_calls"][0]["args"]
    assert set(args) == {"patch"}
    assert "--- a/calc.py" in args["patch"]
    assert "-    return a - b" in args["patch"]
    assert "+    return a + b" in args["patch"]


def test_preparer_keeps_scoped_list_that_is_not_text_artifact_parent() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "docs/hello.txt", "content": "hello"},
            },
            {"tool_name": "list_files", "args": {"path": "fixtures"}},
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python -c \"from pathlib import Path; assert Path('docs/hello.txt').exists()\""
                },
            }
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            allowed_tools=["write_file", "list_files", "run_command"],
            expected_artifacts=["docs/hello.txt"],
            expected_changed_files=["docs/hello.txt"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    assert [call["tool_name"] for call in prepared["tool_calls"]] == ["write_file", "list_files"]


def test_preparer_stabilizes_html_artifact_verification() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "index.html", "content": "<html><body>Hi</body></html>"},
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "echo ok > index.html"},
            }
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            expected_artifacts=["index.html"],
            expected_changed_files=["index.html"],
            allowed_tools=["write_file", "run_command"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    command = prepared["verification"][0]["args"]["command"]
    assert "index.html" in command
    assert ">" not in command


def test_preparer_replaces_unsafe_redirect_with_web_verification() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "styles.css", "content": "body { color: black; }"},
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "type nul > styles.css"},
            }
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            expected_artifacts=["styles.css"],
            expected_changed_files=["styles.css"],
            allowed_tools=["write_file", "run_command"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    commands = [call["args"]["command"] for call in prepared["verification"]]
    assert any("styles.css" in command for command in commands)
    assert all(">" not in command for command in commands)


def test_preparer_rejects_empty_action() -> None:
    with pytest.raises(RuntimeError, match="contained no tool calls"):
        _preparer().prepare(
            {"tool_calls": [], "verification": []},
            _task(
                verification_policy={"required": False, "commands": []},
                expected_artifacts=[],
                expected_changed_files=[],
            ),
            {},
        )


def test_preparer_enforces_required_subagent_only_on_parent_first_round() -> None:
    action = {
        "summary": "inspect directly",
        "tool_calls": [{"tool_name": "read_file", "args": {"path": "input/a.md"}}],
        "verification": [],
        "runtime_requests": [],
        "agent_loop_decision": {
            "schema_version": "0.1.0",
            "decision_id": "agent-loop-decision-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "created_at": "2026-06-08T00:00:00+08:00",
            "next_action": {
                "action": "tool",
                "reason": "inspect directly",
                "target_task_id": "task-0001",
                "capability_ref": {"type": "tool", "name": "read_file"},
                "expected_observation": {},
                "risk": "low",
                "budget_hint": {},
                "evidence_refs": [],
            },
        },
    }
    task = _task(
        allowed_tools=["read_file"],
        read_scope=["input/"],
        write_scope=["reports/review.md"],
        execution_preferences={
            "delegation": "required",
            "requested_capability": "subagent",
            "requested_read_scope": ["input/"],
        },
        verification_policy={"required": False, "commands": []},
    )

    prepared = _preparer().prepare(action, task, {}, round_index=1)
    later = _preparer().prepare(action, task, {}, round_index=2)
    child = _preparer().prepare(
        action,
        {**task, "runtime_profile_hints": {"worker_kind": "subagent"}},
        {},
        round_index=1,
    )

    assert prepared["agent_loop_decision"]["next_action"]["action"] == "subagent"
    assert prepared["agent_loop_decision"]["next_action"]["capability_ref"]["type"] == "subagent"
    assert prepared["tool_calls"] == []
    assert later["agent_loop_decision"]["next_action"]["action"] == "tool"
    assert child["agent_loop_decision"]["next_action"]["action"] == "tool"
