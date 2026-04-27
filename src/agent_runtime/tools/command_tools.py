from __future__ import annotations

import os
import subprocess
import sys

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.shell_guard import ShellGuard
from agent_runtime.tools.base import ToolResult


class RunCommandTool:
    name = "run_command"

    def __init__(self, default_timeout_seconds: int = 60, max_output_chars: int = 20_000) -> None:
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_chars = max_output_chars

    def run(
        self,
        context: RuntimeContext,
        command: str,
        timeout_seconds: int | None = None,
    ) -> ToolResult:
        ShellGuard(context.policy["permissions"]).validate(command)
        timeout = timeout_seconds or self.default_timeout_seconds
        try:
            completed = subprocess.run(
                command,
                cwd=context.root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                ok=False,
                summary=f"Command timed out after {timeout}s: {command}",
                error="timeout",
                data={
                    "stdout": self._truncate(self._text(exc.stdout)),
                    "stderr": self._truncate(self._text(exc.stderr)),
                    "returncode": None,
                },
            )
        stdout = self._truncate(completed.stdout)
        stderr = self._truncate(completed.stderr)
        ok = completed.returncode == 0
        return ToolResult(
            ok=ok,
            summary=f"Command {'passed' if ok else 'failed'} ({completed.returncode}): {command}",
            error=None if ok else "nonzero_exit",
            data={
                "command": command,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": len(completed.stdout) > len(stdout),
                "stderr_truncated": len(completed.stderr) > len(stderr),
            },
        )

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        executable_dir = os.path.dirname(sys.executable)
        env["PATH"] = executable_dir + os.pathsep + env.get("PATH", "")
        return env

    def _text(self, value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n...[truncated]"


class RunTestsTool:
    name = "run_tests"

    def __init__(self, command_tool: RunCommandTool | None = None) -> None:
        self.command_tool = command_tool or RunCommandTool(default_timeout_seconds=120)

    def run(
        self,
        context: RuntimeContext,
        command: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ToolResult:
        test_command = command or context.policy.get("commands", {}).get("test") or "python -m pytest"
        result = self.command_tool.run(context, test_command, timeout_seconds=timeout_seconds)
        result.summary = "Test " + result.summary[0].lower() + result.summary[1:]
        return result
