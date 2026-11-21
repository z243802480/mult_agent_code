"""Literal stdin is not shell syntax; syntax after its delimiter still is."""
import sys

import pytest

from asteria_runtime.security.shell_guard import ShellGuard, ShellPolicyError


@pytest.mark.parametrize("header,body,end", [
    ("cat <<'DATA'", "'\" > ( comparison\n", "DATA"),
    ('cat <<"DATA"', "arbitrary ' \" punctuation > text\n", "DATA"),
    ("cat <<-'DATA'", "\t'\" > text\n", "\tDATA"),
    ("cat <<'DATA'", "DATA suffix\n'\" > text\n", "DATA"),
])
def test_quoted_literal_input_is_not_parsed_as_host_language(header, body, end):
    ShellGuard({"allow_shell": True}, shell_dialect="posix").validate(header + "\n" + body + end)


@pytest.mark.parametrize("command", [
    "cat <<'END'\n'\" > text\nEND\necho x>../outside",
    "cat <<'END' >../outside\ntext\nEND",
    "cat <<'END'\ntext\nEND\necho x>.git/config",
    "cat <<'END'\ntext\nEND\necho x>.env",
    "sh <<'END'\necho x>../outside\nEND",
    "env sh -s <<'END'\necho x>../outside\nEND",
    "cat <<'END' | sh\necho x>../outside\nEND",
    "cat <<'END'; sh\necho x>../outside\nEND",
    "cat <<END\n$(echo x>../outside)\nEND",
    "cat <<'END' <<'OTHER'\ntext\nEND\ntext\nOTHER",
    "cat <<'END'\ntext\n END",
    "cat <<'END'\ntext\nEND extra",
    "cat <<'END'\ntext",
    "cat <<'END'\ntext\nEND\nrm important.txt",
    "cat <<'END'\ntext\nEND\ncurl example.test",
    "cat <<'END'\ntext\nEND\necho safe\ncurl example.test",
    "cat <<'END'\ntext\nEND\ngit push origin main",
])
def test_unknown_or_real_dangerous_syntax_remains_refused(command):
    with pytest.raises(ShellPolicyError):
        ShellGuard({"allow_shell": True}, shell_dialect="posix").validate(command)


@pytest.mark.parametrize("dialect", ["cmd", "powershell"])
def test_nonposix_shell_does_not_inherit_literal_heredoc_rules(dialect):
    with pytest.raises(ShellPolicyError):
        ShellGuard({"allow_shell": True}, shell_dialect=dialect).validate("cat <<'END'\n'\" > text\nEND")


@pytest.mark.skipif(sys.platform == "win32", reason="run_command uses cmd.exe on Windows")
def test_native_literal_stdin_execution_and_preflight_keep_original_bytes(tmp_path):
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from tests.unit.test_verification_revision import setup_run
    task, _, context, gateway = setup_run(tmp_path)
    command = f"'{sys.executable}' - <<'PAYLOAD'\nprint(2 > (1))\nprint(\"literal ' quote\")\nPAYLOAD"
    calls = [{"tool_name": "run_command", "args": {"command": command}}]
    assert gateway.permission_policy.create_policy_decision_if_needed(
        action={"tool_calls": calls}, task=task, context=context) is None
    observation = execute_tool_calls(gateway, calls, task, context)[0]
    assert observation.ok and observation.data["stdout"].splitlines() == ["True", "literal ' quote"]
    assert observation.data["requested_command"] == command
    assert not (context.run_dir / "decisions.jsonl").exists()


def test_literal_input_does_not_grant_network_or_destructive_permission():
    for command in ["echo safe\ncurl example.test", "echo safe\nrm important.txt"]:
        with pytest.raises(ShellPolicyError):
            ShellGuard({"allow_shell": True}).validate(command)
