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


@pytest.mark.parametrize(
    "command",
    [
        "remove-item important.txt",
        "ri important.txt",
        "cmd /c del important.txt",
        "powershell -Command Remove-Item important.txt",
        "python ok.py && del important.txt",
        "python ok.py; Remove-Item important.txt",
        "python ok.py | powershell Remove-Item important.txt",
        "python ok.py > important.txt",
        "git push origin main",
        "git remote add origin https://example.test/repo.git",
        "scp file host:/tmp/file",
        "rsync -a . host:/tmp/project",
        "terraform destroy",
        "kubectl apply -f deploy.yaml",
        "npm install -g package-name",
        "python -m pip install package-name",
    ],
)
def test_shell_guard_blocks_common_bypass_patterns(command: str) -> None:
    guard = ShellGuard(
        {
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_remote_push": False,
            "allow_deploy": False,
            "allow_shell_operators": False,
        }
    )

    with pytest.raises(ShellPolicyError):
        guard.validate(command)


def test_shell_guard_can_allow_shell_operators_when_policy_allows() -> None:
    guard = ShellGuard(
        {
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_remote_push": False,
            "allow_deploy": False,
            "allow_shell_operators": True,
        }
    )

    guard.validate("python --version && python -m compileall -q src")


def test_shell_guard_allows_quoted_python_statement_separator() -> None:
    guard = ShellGuard(
        {
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_remote_push": False,
            "allow_deploy": False,
            "allow_shell_operators": False,
        }
    )

    guard.validate('python -c "from math import sqrt; assert sqrt(4) == 2"')
