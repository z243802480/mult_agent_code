from agent_runtime.core.task_contract import (
    allows_expected_failure,
    check_completion_contract,
    requires_changed_artifact,
    task_kind,
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
