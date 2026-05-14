from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.core.task_contract import parallel_safety, write_scope


@dataclass(frozen=True)
class SandboxBackendPlan:
    backend: str
    workspace_policy: str
    reason: str


class SandboxBackendSelector:
    def select_for_task(self, source_root: Path, task: dict) -> SandboxBackendPlan:
        if parallel_safety(task) == "readonly" or not write_scope(task):
            return SandboxBackendPlan(
                backend="single_workspace",
                workspace_policy="controlled_patch",
                reason="readonly task has no writable scope",
            )
        return self.select_for_workspace(source_root)

    def select_for_workspace(self, source_root: Path) -> SandboxBackendPlan:
        if self.can_use_git_worktree(source_root):
            return SandboxBackendPlan(
                backend="git_worktree",
                workspace_policy="worktree",
                reason="clean git workspace supports detached worktree isolation",
            )
        return SandboxBackendPlan(
            backend="temp_workspace",
            workspace_policy="isolated_copy",
            reason="use copied temp workspace when git worktree is unavailable",
        )

    def can_use_git_worktree(self, source_root: Path) -> bool:
        if not (source_root / ".git").exists():
            return False
        try:
            status = self._run_git(source_root, "status", "--porcelain")
        except (OSError, subprocess.SubprocessError):
            return False
        return not status.stdout.strip()

    def _run_git(self, source_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=source_root,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
