from asteria_runtime.core.task_contract import (
    allows_expected_failure,
    check_completion_contract,
    context_requirements,
    failure_policy,
    parallel_safety,
    path_in_read_scope,
    path_in_write_scope,
    read_scope,
    requires_changed_artifact,
    task_kind,
    validation_commands,
    write_scope,
)


def test_task_contract_uses_explicit_task_kind_and_completion_contract() -> None:
    task = {
        "task_kind": "diagnostic",
        "completion_contract": {
            "requires_changed_artifact": False,
            "requires_verification": True,
            "allows_expected_failure": True,
        },
    }

    assert task_kind(task) == "diagnostic"
    assert allows_expected_failure(task) is True
    assert requires_changed_artifact(task) is False


def test_task_contract_infers_implementation_for_legacy_tasks() -> None:
    task = {
        "title": "Fix parser bug",
        "description": "Update parser implementation",
        "acceptance": ["parser handles input"],
        "expected_artifacts": ["parser.py"],
    }

    assert task_kind(task) == "implementation"
    assert requires_changed_artifact(task) is True
    assert allows_expected_failure(task) is False


class _Result:
    def __init__(self, ok: bool) -> None:
        self.ok = ok


def test_completion_contract_requires_verification_and_expected_file_change() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(task, ["notes_tool.py"], [_Result(True)])

    assert check.ok is False
    assert check.expected_changed_files == ["password_strength.py"]
    assert "expected changed files were not modified" in check.violations[0]


def test_completion_contract_passes_when_expected_file_is_changed_and_verified() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(task, ["password_strength.py"], [_Result(True)])

    assert check.ok is True
    assert check.summary() == "Task completion contract satisfied."


def test_completion_contract_can_allow_verified_noop_for_repair_closure() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(
        task,
        [],
        [_Result(True)],
        allow_verified_noop=True,
    )

    assert check.ok is True


def test_task_contract_exposes_runtime_scopes_and_policies() -> None:
    task = {
        "task_kind": "implementation",
        "expected_artifacts": ["src/asteria_runtime/example.py"],
        "expected_changed_files": ["src/asteria_runtime/example.py"],
        "verification_policy": {"commands": ["pytest tests/unit/test_example.py"]},
    }

    assert read_scope(task) == [
        "AGENTS.md",
        "src/asteria_runtime/example.py",
        "src/asteria_runtime",
    ]
    assert write_scope(task) == ["src/asteria_runtime/example.py"]
    assert validation_commands(task) == ["pytest tests/unit/test_example.py"]
    assert failure_policy(task) == "create_repair_task"
    assert parallel_safety(task) == "serial"
    assert context_requirements(task)["mount_type"] == "coding_context"


def test_task_contract_marks_tasks_without_write_scope_as_readonly() -> None:
    task = {
        "task_kind": "research",
        "title": "Research architecture",
        "expected_artifacts": ["docs/notes.md"],
    }

    assert write_scope(task) == []
    assert parallel_safety(task) == "readonly"
    assert failure_policy(task) == "continue_other_branches"


def test_path_in_write_scope_accepts_implementation_artifact_for_src_paths() -> None:
    scope = ["implementation artifact"]
    assert path_in_write_scope("src/notes_tool.py", scope, kind="implementation") is True
    assert path_in_write_scope("blocked/output.txt", scope, kind="implementation") is False


def test_path_in_read_scope_accepts_src_directory_for_implementation_artifact() -> None:
    scope = ["AGENTS.md", "implementation artifact"]
    assert path_in_read_scope("src", scope, kind="implementation") is True
    assert path_in_read_scope("secrets/key.txt", scope, kind="implementation") is False
