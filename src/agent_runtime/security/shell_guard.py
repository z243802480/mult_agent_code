from __future__ import annotations

import shlex


class ShellPolicyError(PermissionError):
    pass


class ShellGuard:
    DESTRUCTIVE_TOKENS = {
        "rm",
        "del",
        "erase",
        "rmdir",
        "Remove-Item",
        "rd",
        "format",
        "shutdown",
        "reboot",
    }
    REMOTE_TOKENS = {"git push", "deploy", "scp", "rsync"}
    GLOBAL_INSTALL_PATTERNS = {
        "npm install -g",
        "pip install",
        "uv pip install --system",
    }

    def __init__(self, permissions: dict) -> None:
        self.permissions = permissions

    def validate(self, command: str) -> None:
        if not self.permissions.get("allow_shell", False):
            raise ShellPolicyError("Shell commands are disabled by policy")

        lowered = command.lower()
        tokens = self._tokens(command)

        if not self.permissions.get("allow_destructive_shell", False):
            for token in tokens:
                if token in self.DESTRUCTIVE_TOKENS or token.lower() in {
                    item.lower() for item in self.DESTRUCTIVE_TOKENS
                }:
                    raise ShellPolicyError(f"Destructive shell command denied: {token}")

        if not self.permissions.get("allow_remote_push", False) and "git push" in lowered:
            raise ShellPolicyError("Remote push is denied by policy")

        if not self.permissions.get("allow_deploy", False):
            for token in self.REMOTE_TOKENS:
                if token in lowered:
                    raise ShellPolicyError(f"Deployment/remote command denied: {token}")

        if not self.permissions.get("allow_global_package_install", False):
            for pattern in self.GLOBAL_INSTALL_PATTERNS:
                if pattern in lowered:
                    raise ShellPolicyError(f"Global/system package install denied: {pattern}")

    def _tokens(self, command: str) -> list[str]:
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return command.split()
