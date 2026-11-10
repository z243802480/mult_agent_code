"""Facts about the command environment exposed to planning and execution models."""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def command_execution_context(root: Path | None = None) -> dict[str, str | bool]:
    """Describe the shell used by ``run_command`` (process_fence uses shell=True)."""
    host_os = platform.system()
    context: dict[str, str | bool] = {
        "host_os": host_os,
        "run_command_shell": "cmd.exe" if host_os == "Windows" else "/bin/sh",
        "harness_python_executable": sys.executable,
    }
    if root is not None:
        resolved = root.resolve()
        # Presence only: never inspect Git metadata or credentials. A .git file is
        # also valid (worktree), and a nested working directory inherits its repo.
        context["git_repository_detected"] = any(
            (parent / ".git").exists() for parent in (resolved, *resolved.parents)
        )
    return context
