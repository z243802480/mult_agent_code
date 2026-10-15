"""Facts about the command environment exposed to planning and execution models."""

from __future__ import annotations

import platform
import sys


def command_execution_context() -> dict[str, str]:
    """Describe the shell used by ``run_command`` (process_fence uses shell=True)."""
    host_os = platform.system()
    return {
        "host_os": host_os,
        "run_command_shell": "cmd.exe" if host_os == "Windows" else "/bin/sh",
        "harness_python_executable": sys.executable,
    }
