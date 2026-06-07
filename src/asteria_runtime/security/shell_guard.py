from __future__ import annotations

import re
import shlex


class ShellPolicyError(PermissionError):
    pass


class ShellGuard:
    DESTRUCTIVE_COMMANDS = {
        "rm",
        "del",
        "erase",
        "rmdir",
        "remove-item",
        "ri",
        "rd",
        "format",
        "shutdown",
        "reboot",
        "restart-computer",
        "stop-computer",
    }
    REMOTE_COMMANDS = {
        "scp",
        "rsync",
    }
    REMOTE_PATTERNS = {
        "git push",
        "git remote add",
        "git remote set-url",
    }
    DEPLOY_PATTERNS = {
        "deploy",
        "kubectl apply",
        "kubectl delete",
        "terraform apply",
        "terraform destroy",
        "vercel deploy",
        "netlify deploy",
    }
    GLOBAL_INSTALL_PATTERNS = {
        "npm install -g",
        "pnpm add -g",
        "yarn global add",
        "pip install",
        "python -m pip install",
        "py -m pip install",
        "uv pip install --system",
    }
    CONTROL_OPERATORS = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>"}
    OUTPUT_REDIRECT_OPERATORS = {">", ">>"}
    UNSAFE_CONTROL_OPERATORS = CONTROL_OPERATORS - OUTPUT_REDIRECT_OPERATORS

    def __init__(self, permissions: dict) -> None:
        self.permissions = permissions

    def validate(self, command: str) -> None:
        if not self.permissions.get("allow_shell", False):
            raise ShellPolicyError("Shell commands are disabled by policy")

        normalized = self._normalize(command)
        tokens = self._tokens(command)
        token_words = self._command_words(tokens)

        if not self.permissions.get("allow_shell_operators", False):
            self._validate_output_redirects(command)
            for operator in self.UNSAFE_CONTROL_OPERATORS:
                if operator in tokens:
                    raise ShellPolicyError(f"Shell control operator denied: {operator}")

        if not self.permissions.get("allow_destructive_shell", False):
            for word in token_words:
                if word in self.DESTRUCTIVE_COMMANDS:
                    raise ShellPolicyError(f"Destructive shell command denied: {word}")

        if not self.permissions.get("allow_remote_push", False):
            for pattern in self.REMOTE_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Remote git command denied: {pattern}")

        if not self.permissions.get("allow_deploy", False):
            for word in token_words:
                if word in self.REMOTE_COMMANDS:
                    raise ShellPolicyError(f"Deployment/remote command denied: {word}")
            for pattern in self.DEPLOY_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Deployment/remote command denied: {pattern}")

        if not self.permissions.get("allow_global_package_install", False):
            for pattern in self.GLOBAL_INSTALL_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Global/system package install denied: {pattern}")

    def _validate_output_redirects(self, command: str) -> None:
        for match in re.finditer(r'(?:^|\s)(>>|>)\s+("?)([^"\s;|&<>]+)\2', command):
            target = match.group(3)
            if not self._safe_redirect_target(target):
                raise ShellPolicyError(f"Shell output redirect denied: {target}")

    def _safe_redirect_target(self, target: str) -> bool:
        cleaned = target.strip().strip('"').strip("'")
        if not cleaned or ".." in cleaned:
            return False
        if cleaned.startswith(("/", "\\", "$", "%", "~")):
            return False
        if any(char in cleaned for char in "|;&<>()"):
            return False
        return True

    def _tokens(self, command: str) -> list[str]:
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return command.split()

    def _command_words(self, tokens: list[str]) -> list[str]:
        words = []
        wrappers = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
        wrapper_flags = {"/c", "-command", "-c", "-encodedcommand", "-enc", "-nop", "-noprofile"}
        for token in tokens:
            cleaned = token.strip().strip('"').strip("'")
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in wrappers or lowered in wrapper_flags:
                continue
            if lowered.startswith("-") or lowered.startswith("/"):
                continue
            words.append(lowered)
        return words

    def _normalize(self, command: str) -> str:
        lowered = command.lower()
        spaced = re.sub(r"[\r\n\t]+", " ", lowered)
        return re.sub(r"\s+", " ", spaced).strip()
