from agent_runtime.core.task_contract import (
    allows_expected_failure,
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
