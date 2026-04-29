from __future__ import annotations

import os
import re
import shlex
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
        expected_returncodes: int | list[int] | None = None,
    ) -> ToolResult:
        ShellGuard(context.policy["permissions"]).validate(command)
        normalized_command = self._normalize_command(command)
        ShellGuard(context.policy["permissions"]).validate(normalized_command)
        timeout = timeout_seconds or self.default_timeout_seconds
        try:
            completed = subprocess.run(
                normalized_command,
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
        expected = self._expected_returncodes(expected_returncodes)
        ok = completed.returncode in expected or self._is_usage_check(command, completed)
        summary_command = (
            f"{normalized_command} (normalized from: {command})"
            if normalized_command != command
            else command
        )
        return ToolResult(
            ok=ok,
            summary=f"Command {'passed' if ok else 'failed'} ({completed.returncode}): {summary_command}",
            error=None if ok else "nonzero_exit",
            data={
                "command": normalized_command,
                "requested_command": command,
                "returncode": completed.returncode,
                "expected_returncodes": sorted(expected),
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

    def _normalize_command(self, command: str) -> str:
        normalized = self._normalize_python_invocation(command)
        if os.name == "nt":
            normalized = self._normalize_windows_ls(normalized)
        return normalized

    def _normalize_python_invocation(self, command: str) -> str:
        match = re.match(r"^(\s*)(python3|python)(\s|$)(.*)$", command, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return command
        prefix, _python_name, separator, rest = match.groups()
        executable = self._shell_quote(sys.executable)
        if separator:
            return f"{prefix}{executable}{separator}{rest}"
        return f"{prefix}{executable}"

    def _normalize_windows_ls(self, command: str) -> str:
        match = re.match(r"^\s*ls\s+-la\s+(.+?)\s*$", command, flags=re.IGNORECASE)
        if not match:
            return command
        raw_path = match.group(1).strip().strip('"').strip("'")
        escaped = raw_path.replace("\\", "\\\\").replace("'", "\\'")
        executable = self._shell_quote(sys.executable)
        return (
            f"{executable} -c \"from pathlib import Path; import sys; "
            f"sys.exit(0 if Path('{escaped}').exists() else 1)\""
        )

    def _shell_quote(self, value: str) -> str:
        if os.name == "nt":
            return subprocess.list2cmdline([value])
        return shlex.quote(value)

    def _expected_returncodes(self, value: int | list[int] | None) -> set[int]:
        if value is None:
            return {0}
        if isinstance(value, int):
            return {value}
        return {int(item) for item in value}

    def _is_usage_check(
        self,
        command: str,
        completed: subprocess.CompletedProcess[str],
    ) -> bool:
        if completed.returncode == 0:
            return False
        normalized = command.strip().lower()
        if not re.match(r"^(python3?|py)\s+[\w./\\-]+\.py\s*$", normalized):
            return False
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        return "usage:" in output

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
        expected_returncodes: int | list[int] | None = None,
    ) -> ToolResult:
        test_command = command or context.policy.get("commands", {}).get("test") or "python -m pytest"
        result = self.command_tool.run(
            context,
            test_command,
            timeout_seconds=timeout_seconds,
            expected_returncodes=expected_returncodes,
        )
        result.summary = "Test " + result.summary[0].lower() + result.summary[1:]
        return result
