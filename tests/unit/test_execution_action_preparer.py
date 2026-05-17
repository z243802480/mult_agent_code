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
    assert prepared["verification"][0]["args"]["command"] == "python -m py_compile tool.py"
    assert prepared["verification"][1]["args"]["command"] == "python tool.py --help"


def test_preparer_uses_planned_verification_when_required_action_omits_it() -> None:
    action = {
        "tool_calls": [
            {"tool_name": "write_file", "args": {"path": "tool.py", "content": "print('ok')"}},
        ],
        "verification": [],
    }

    prepared = _preparer().prepare(action, _task(), {})

    assert [call["args"]["command"] for call in prepared["verification"]] == [
        "python -m py_compile tool.py",
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
        "python -m py_compile tool.py",
        "python tool.py --help",
    ]


def test_preparer_replaces_doc_only_verification_with_stable_file_check() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"path": "docs/gray_batch_note.md", "content": "# Gray\n"},
            },
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        'python -c "from pathlib import Path; '
                        'paths=["docs/gray_batch_note.md"]; print(paths)"'
                    )
                },
            },
        ],
    }

    prepared = _preparer().prepare(
        action,
        _task(
            expected_artifacts=["docs/gray_batch_note.md"],
            expected_changed_files=["docs/gray_batch_note.md"],
            verification_policy={"required": True, "commands": []},
        ),
        {},
    )

    commands = [call["args"]["command"] for call in prepared["verification"]]
    assert len(commands) == 1
    assert "docs/gray_batch_note.md" in commands[0]
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
