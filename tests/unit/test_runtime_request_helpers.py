from __future__ import annotations

from asteria_runtime.core.runtime_request import (
    apply_runtime_request_to_task,
    effective_runtime_request_risk,
    is_benign_workspace_scope,
)


def test_is_benign_workspace_scope_accepts_root_level_py_files() -> None:
    assert is_benign_workspace_scope(["greet_cli.py", "test_greet_cli.py"])


def test_is_benign_workspace_scope_rejects_nested_or_unsafe_paths() -> None:
    assert not is_benign_workspace_scope(["blocked/output.txt"])
    assert not is_benign_workspace_scope(["../secrets.py"])
    assert not is_benign_workspace_scope([".env"])


def test_effective_runtime_request_risk_downgrades_benign_scope_for_reviewed_auto() -> None:
    request = {
        "request_type": "scope_expansion",
        "risk": "medium",
        "details": {"write_scope": ["greet_cli.py"]},
    }
    assert effective_runtime_request_risk(request, auto_allow_low_risk=True) == "low"
    assert effective_runtime_request_risk(request, auto_allow_low_risk=False) == "medium"


def test_apply_runtime_request_to_task_merges_write_scope() -> None:
    task = {"task_id": "task-0001", "write_scope": ["allowed/"]}
    changed = apply_runtime_request_to_task(
        task,
        {
            "request_type": "scope_expansion",
            "details": {"write_scope": ["greet_cli.py"]},
        },
    )
    assert changed
    assert "greet_cli.py" in task["write_scope"]
