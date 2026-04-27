from pathlib import Path

import pytest

from agent_runtime.security.path_guard import PathGuard, PathPolicyError
from agent_runtime.security.shell_guard import ShellGuard, ShellPolicyError


def test_path_guard_blocks_escaping_root(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path, [".env", "secrets/"])

    with pytest.raises(PathPolicyError):
        guard.resolve_for_read(tmp_path.parent / "outside.txt")


def test_path_guard_blocks_protected_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    guard = PathGuard(tmp_path, [".env", "secrets/"])

    with pytest.raises(PathPolicyError):
        guard.resolve_for_read(".env")


def test_shell_guard_blocks_destructive_command() -> None:
    guard = ShellGuard(
        {
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        }
    )

    with pytest.raises(ShellPolicyError):
        guard.validate("Remove-Item important.txt")


def test_shell_guard_allows_safe_command() -> None:
    guard = ShellGuard(
        {
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        }
    )

    guard.validate("python --version")
