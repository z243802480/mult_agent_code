from __future__ import annotations

import os
import subprocess
import sys

from asteria_runtime.core.process_fence import run_fenced
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.sandbox_launch import run_sandboxed
from asteria_runtime.core.sandbox_provision import (
    SandboxContext,
    SandboxUnavailable,
    ensure_sandbox,
    sandbox_supported,
)
from asteria_runtime.security.env_sanitizer import sanitize_subprocess_env
from asteria_runtime.security.shell_guard import ShellGuard
from asteria_runtime.tools.base import ToolResult


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
        permissions = context.policy["permissions"]
        protected_paths = context.policy.get("protected_paths")
        ShellGuard(permissions, protected_paths).validate(command)
        timeout = timeout_seconds or self.default_timeout_seconds

        # ADR-0030 S-B: when the policy opts into sandbox_shell, the command runs inside an
        # AppContainer that denies network egress and confines writes to the workspace at the OS
        # layer. Fail-closed: if the sandbox was required but can't be built, the command FAILS —
        # never a silent fall-through to an unsandboxed run, which would make "network is off" a lie.
        sandbox_ctx: SandboxContext | None = None
        if permissions.get("sandbox_shell", False):
            if not sandbox_supported():
                return self._sandbox_unavailable(
                    command, "sandbox_shell is required but the AppContainer sandbox is not "
                    "available on this platform (Windows only)"
                )
            try:
                sandbox_ctx = ensure_sandbox(str(context.root))
            except SandboxUnavailable as exc:
                return self._sandbox_unavailable(command, str(exc))

        try:
            if sandbox_ctx is not None:
                completed = run_sandboxed(
                    sandbox_ctx,
                    command,
                    cwd=str(context.root),
                    env=self._env(),
                    timeout=timeout,
                    allow_network=bool(permissions.get("allow_network", False)),
                )
            else:
                # ADR-0030 S-A: run inside an OS process fence (Job Object / process group) so the
                # whole tree — including detached children the static ShellGuard can't see — dies
                # with the run.
                completed = run_fenced(
                    command,
                    cwd=context.root,
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
        raw_stdout = self._text(completed.stdout)
        raw_stderr = self._text(completed.stderr)
        stdout = self._truncate(raw_stdout)
        stderr = self._truncate(raw_stderr)
        expected = self._expected_returncodes(expected_returncodes)
        ok = completed.returncode in expected
        return ToolResult(
            ok=ok,
            summary=f"Command {'passed' if ok else 'failed'} ({completed.returncode}): {command}",
            error=None if ok else "nonzero_exit",
            data={
                "command": command,
                "requested_command": command,
                "returncode": completed.returncode,
                "expected_returncodes": sorted(expected),
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": len(raw_stdout) > len(stdout),
                "stderr_truncated": len(raw_stderr) > len(stderr),
            },
        )

    def _sandbox_unavailable(self, command: str, reason: str) -> ToolResult:
        # Fail-closed refusal: the policy asked for a sandbox and one could not be built. The command
        # did NOT run — better a visible failure than a silent unsandboxed execution.
        return ToolResult(
            ok=False,
            summary=f"Sandbox required but unavailable — command not run: {command}",
            error="sandbox_unavailable",
            data={"command": command, "reason": reason, "returncode": None},
        )

    def _env(self) -> dict[str, str]:
        # Strip the harness's own provider credentials (and any *_API_KEY/*_TOKEN/*_SECRET/
        # password) from the child shell: the ShellGuard denylist cannot contain an interpreter
        # payload, so we remove the secret rather than hope to block every exfil command.
        env, _removed = sanitize_subprocess_env()
        executable_dir = os.path.dirname(sys.executable)
        # Keep a project's active environment ahead of the harness interpreter. The latter is
        # only a fallback when no earlier PATH entry provides Python.
        env["PATH"] = os.pathsep.join(part for part in (env.get("PATH", ""), executable_dir) if part)
        return env

    def _expected_returncodes(self, value: int | list[int] | None) -> set[int]:
        if value is None:
            return {0}
        if isinstance(value, int):
            return {value}
        return {int(item) for item in value}

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
        result = self.command_tool.run(
            context,
            test_command,
            timeout_seconds=timeout_seconds,
        )
        result.summary = "Test " + result.summary[0].lower() + result.summary[1:]
        return result
