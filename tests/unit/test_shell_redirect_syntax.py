"""Quoting changes shell syntax, never the permission of a real redirect target."""
import pytest

from asteria_runtime.security.shell_guard import ShellGuard, ShellPolicyError


def test_host_quoted_argument_is_not_an_output_redirect():
    ShellGuard({"allow_shell": True}).validate('python -c "print(2 > (1))"')


@pytest.mark.parametrize("dialect,command", [
    ("posix", "python -c 'print(2 > (1))'"),
    ("posix", 'python -c "print(2 > (1))"'),
    ("cmd", 'python -c "print(2 > (1))"'),
    ("powershell", "Write-Output 'x > ../not-a-target'"),
    ("powershell", 'Write-Output "x > ../not-a-target"'),
    ("posix", r"echo \>../literal"),
    ("cmd", "echo ^>../literal"),
    ("powershell", "Write-Output `>../literal"),
    ("posix", "echo ok > 'report with spaces.txt'"),
    ("cmd", 'echo ok>"report with spaces.txt"'),
    ("posix", "echo ok 2>&1"),
    ("cmd", "echo ok 2>&1"),
    ("powershell", "Write-Output ok 2>&1"),
    ("posix", "sh -c 'python -c \"print(2 > (1))\"'"),
    ("posix", "sh -c 'printf \"%s\\n\" \"value > (1)\"'"),
])
def test_shell_literals_and_safe_targets(dialect, command):
    ShellGuard({"allow_shell": True}, shell_dialect=dialect).validate(command)


@pytest.mark.parametrize("dialect,command", [
    ("cmd", "python -c 'print(2 > (1))'"),
    ("posix", "echo ok>../outside"),
    ("cmd", "echo ok>..\\outside"),
    ("posix", "echo ok 2>../outside"),
    ("cmd", 'echo ok>>"../outside with spaces"'),
    ("powershell", "Write-Output ok *> ../outside"),
    ("posix", "echo ok> .env"),
    ("posix", "echo ok>.git/config"),
    ("cmd", 'echo ok>"C:\\outside.txt"'),
    ("posix", "sh -c 'echo ok>../outside'"),
    ("posix", "eval 'echo ok>../outside'"),
    ("posix", "timeout 2 sh -c 'echo ok>../outside'"),
    ("posix", "bash -lc 'echo ok 2>../outside'"),
    ("posix", "cmd /c 'echo ok>../outside'"),
    ("posix", "pwsh -Command 'Write-Output ok > ../outside'"),
    ("posix", "pwsh -Com 'Write-Output ok > ../outside'"),
    ("posix", "echo ok > prefix$TARGET"),
    ("cmd", "echo ok > prefix%TARGET%"),
    ("posix", "cat <<'END'\n'\nEND\necho ok > ../outside\n'"),
    ("cmd", 'cmd /c "echo ok>../outside"'),
    ("cmd", 'powershell -Command "Write-Output ok > ../outside"'),
    ("posix", 'echo "$(echo ok>../outside)"'),
    ("posix", 'echo "`echo ok>../outside`"'),
    ("posix", 'sh -c "$SCRIPT"'),
    ("posix", "pwsh -EncodedCommand ZQBjAGgAbwAgAHgA"),
    ("posix", 'echo "unclosed > ../outside'),
])
def test_real_or_unresolved_redirects_still_refused(dialect, command):
    with pytest.raises(ShellPolicyError):
        ShellGuard({"allow_shell": True}, shell_dialect=dialect).validate(command)


@pytest.mark.parametrize("command", [
    "echo ok > ../outside", "echo ok>.env", "sh -c 'echo ok>.git/config'",
])
def test_quote_fix_does_not_change_policy_permissions(command):
    policy = {"allow_shell": True}
    with pytest.raises(ShellPolicyError):
        ShellGuard(policy, shell_dialect="posix").validate(command)
    assert policy == {"allow_shell": True}
