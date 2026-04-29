from agent_runtime.agents.execution_action import normalize_execution_action


def test_normalize_execution_action_fills_required_context_fields() -> None:
    action = {
        "summary": "verify file",
        "tool_calls": [
            {
                "name": "read_file",
                "arguments": {"path": "hello_runtime.txt"},
                "reason": "check content",
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0002"})

    assert normalized["schema_version"] == "0.1.0"
    assert normalized["task_id"] == "task-0002"
    assert normalized["tool_calls"] == [
        {
            "tool_name": "read_file",
            "args": {"path": "hello_runtime.txt"},
            "reason": "check content",
        }
    ]
    assert normalized["verification"] == []


def test_normalize_execution_action_repairs_obvious_write_file_args() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"content": "real model smoke ok"},
            }
        ],
    }
    task = {
        "task_id": "task-0001",
        "title": "Create file named 'hello_runtime.txt'",
        "description": "Create file named hello_runtime.txt",
        "acceptance": ["File contains 'real model smoke ok'"],
    }

    normalized = normalize_execution_action(action, task)

    assert normalized["tool_calls"][0]["args"] == {
        "path": "hello_runtime.txt",
        "content": "real model smoke ok",
        "overwrite": True,
    }


def test_normalize_execution_action_removes_nonportable_success_suffix() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python markdown_kb.py 2>&1 || true",
                    "expected_returncodes": [0, 1],
                },
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})

    assert normalized["verification"][0]["args"] == {
        "command": "python markdown_kb.py",
        "expected_returncodes": [0, 1],
    }


def test_normalize_execution_action_rewrites_shell_fixture_setup() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        'mkdir -p test_nested/subdir/.hidden/deeper && echo "Python is great" > '
                        'test_nested/file1.md && echo "python test" > test_nested/subdir/file2.md'
                    ),
                },
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})
    command = normalized["verification"][0]["args"]["command"]

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert " > " not in command


def test_normalize_execution_action_rewrites_fixture_setup_before_python_command() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": 'echo "binary content" > /tmp/test_md_search/binary.bin && python markdown_kb.py /tmp/test_md_search python',
                    "expected_returncodes": [0],
                },
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})
    command = normalized["verification"][0]["args"]["command"]

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert " > " not in command
    assert "subprocess.run" in command


def test_normalize_execution_action_rewrites_cd_tmp_fixture_setup() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        'cd /tmp && mkdir -p test_md_search && echo -e "# Python Guide\\nBody" > '
                        "test_md_search/docs.md && python /tmp/markdown_kb.py test_md_search Python"
                    ),
                },
            }
        ],
    }
    task = {"task_id": "task-0001", "expected_artifacts": ["markdown_kb.py"]}

    normalized = normalize_execution_action(action, task)
    command = normalized["verification"][0]["args"]["command"]

    assert command.startswith('python -c "')
    assert "cd /tmp" not in command
    assert "&&" not in command
    assert "L3RtcC9tYXJrZG93bl9rYi5weQ==" not in command
    assert "subprocess.run" in command


def test_normalize_execution_action_ignores_fixture_status_echo() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        "mkdir -p /tmp/test_md/.git/nested && echo '# Hello World' > "
                        "/tmp/test_md/test1.md && echo 'Test complete'"
                    ),
                },
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})
    command = normalized["verification"][0]["args"]["command"]

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert "Test complete" not in command


def test_normalize_execution_action_rewrites_safe_test_cleanup() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "rm -rf test_markdown"},
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})
    command = normalized["verification"][0]["args"]["command"]

    assert command.startswith('python -c "')
    assert "rm -rf" not in command
    assert "shutil.rmtree" in command


def test_normalize_execution_action_does_not_rewrite_unsafe_cleanup() -> None:
    action = {
        "verification": [
            {
                "tool_name": "run_command",
                "args": {"command": "rm -rf ../secrets"},
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0001"})

    assert normalized["verification"][0]["args"]["command"] == "rm -rf ../secrets"
