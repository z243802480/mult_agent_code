from agent_runtime.agents.verification_command_normalizer import normalize_verification_command


def test_normalize_verification_command_removes_nonportable_success_suffix() -> None:
    command = normalize_verification_command(
        "python markdown_kb.py 2>&1 || true",
        {"task_id": "task-0001"},
    )

    assert command == "python markdown_kb.py"


def test_normalize_verification_command_rewrites_shell_fixture_setup() -> None:
    command = normalize_verification_command(
        (
            'mkdir -p test_nested/subdir/.hidden/deeper && echo "Python is great" > '
            'test_nested/file1.md && echo "python test" > test_nested/subdir/file2.md'
        ),
        {"task_id": "task-0001"},
    )

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert " > " not in command


def test_normalize_verification_command_rewrites_fixture_setup_before_python_command() -> None:
    command = normalize_verification_command(
        'echo "binary content" > /tmp/test_md_search/binary.bin && python markdown_kb.py /tmp/test_md_search python',
        {"task_id": "task-0001"},
    )

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert " > " not in command
    assert "subprocess.run" in command


def test_normalize_verification_command_rewrites_cd_tmp_fixture_setup() -> None:
    command = normalize_verification_command(
        (
            'cd /tmp && mkdir -p test_md_search && echo -e "# Python Guide\\nBody" > '
            "test_md_search/docs.md && python /tmp/markdown_kb.py test_md_search Python"
        ),
        {"task_id": "task-0001", "expected_artifacts": ["markdown_kb.py"]},
    )

    assert command.startswith('python -c "')
    assert "cd /tmp" not in command
    assert "&&" not in command
    assert "L3RtcC9tYXJrZG93bl9rYi5weQ==" not in command
    assert "subprocess.run" in command


def test_normalize_verification_command_ignores_fixture_status_echo() -> None:
    command = normalize_verification_command(
        (
            "mkdir -p /tmp/test_md/.git/nested && echo '# Hello World' > "
            "/tmp/test_md/test1.md && echo 'Test complete'"
        ),
        {"task_id": "task-0001"},
    )

    assert command.startswith('python -c "')
    assert "&&" not in command
    assert "Test complete" not in command


def test_normalize_verification_command_rewrites_safe_test_cleanup() -> None:
    command = normalize_verification_command(
        "rm -rf test_markdown",
        {"task_id": "task-0001"},
    )

    assert command.startswith('python -c "')
    assert "rm -rf" not in command
    assert "shutil.rmtree" in command


def test_normalize_verification_command_does_not_rewrite_unsafe_cleanup() -> None:
    command = normalize_verification_command(
        "rm -rf ../secrets",
        {"task_id": "task-0001"},
    )

    assert command == "rm -rf ../secrets"
