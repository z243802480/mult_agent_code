from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime.core.sandbox_backend import SandboxBackendSelector


def test_sandbox_backend_selector_uses_temp_workspace_without_git(tmp_path: Path) -> None:
    plan = SandboxBackendSelector().select_for_workspace(tmp_path)

    assert plan.backend == "temp_workspace"
    assert plan.workspace_policy == "isolated_copy"
    assert plan.reason


def test_sandbox_backend_selector_keeps_readonly_in_single_workspace(tmp_path: Path) -> None:
    task = {"parallel_safety": "readonly", "write_scope": []}

    plan = SandboxBackendSelector().select_for_task(tmp_path, task)

    assert plan.backend == "single_workspace"
    assert plan.workspace_policy == "controlled_patch"


def test_sandbox_backend_selector_prefers_git_worktree_for_clean_repo(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    try:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "agent@example.test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Agent Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "add", "tool.py"], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git unavailable: {exc}")

    plan = SandboxBackendSelector().select_for_workspace(tmp_path)

    assert plan.backend == "git_worktree"
    assert plan.workspace_policy == "worktree"
