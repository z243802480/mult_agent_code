from __future__ import annotations

import subprocess

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
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                ok=False,
                summary=f"Command timed out after {timeout}s: {command}",
                error="timeout",
                data={
                    "stdout": self._truncate(exc.stdout or ""),
                    "stderr": self._truncate(exc.stderr or ""),
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
