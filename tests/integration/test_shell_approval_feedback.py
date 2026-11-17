"""Preflight, execution and user approval inspect the same unmodified command."""
from copy import deepcopy
from dataclasses import replace
import sys

import pytest

from asteria_runtime.core.model_driven_turn import execute_tool_calls, _observation_feedback
from asteria_runtime.storage.jsonl_store import JsonlStore
from tests.unit.test_verification_revision import setup_run


COMMAND = f'"{sys.executable}" -c "print(2 > (1))"'


def action(command=COMMAND, **extra):
    return {"tool_calls": [{"tool_name": "run_command", "args": {"command": command, **extra}}]}


def test_quoted_comparison_preflight_and_actual_execution_share_exact_command(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    before = deepcopy(context.policy)
    policy = gateway.permission_policy
    assert policy.create_policy_decision_if_needed(action=action(), task=task, context=context) is None
    observed = execute_tool_calls(gateway, action()["tool_calls"], task, context)[0]
    assert observed.ok and observed.data["stdout"].strip().splitlines()[-1] == "True"
    assert observed.data["requested_command"] == COMMAND
    assert observed.dispatch_state == "dispatched"
    assert context.policy == before and not (context.run_dir / "decisions.jsonl").exists()


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("selection", ["skip", "approve_once"])
def test_approval_receipt_and_resolution_keep_exact_boundary(tmp_path, explicit, selection):
    task, _, context, gateway = setup_run(tmp_path)
    context = replace(context, policy={**context.policy, "permissions": {"allow_shell": False}})
    policy = gateway.permission_policy
    original = deepcopy(context.policy)
    args = action()["tool_calls"][0]["args"]
    request = action() if not explicit else {"tool_calls": [{"tool_name": "request_execution_permission",
        "args": {"tool_name": "run_command", "args": args, "reason": "Run this exact check"}}]}
    pending = policy.create_policy_decision_if_needed(action=request, task=task, context=context)
    assert pending and pending["status"] == "pending"
    assert COMMAND in pending["question"]
    receipt = pending["metadata"]["execution_request"]
    assert receipt["args"] == args and receipt["dispatch_state"] == "not_dispatched"
    assert receipt["shell"] == ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
    assert not (context.run_dir / "tool_calls.jsonl").exists()
    assert not policy.has_execution_approval(context, task, "run_command", args)
    pending.update(status="resolved", selected_option_id=selection)
    JsonlStore(context.validator).rewrite_all(context.run_dir / "decisions.jsonl", [pending], "decision_point")
    assert policy.create_policy_decision_if_needed(action=action(), task=task, context=context) is None
    obs = execute_tool_calls(gateway, action()["tool_calls"], task, context)[0]
    if selection == "skip":
        assert not obs.ok and obs.dispatch_state == "not_dispatched"
        assert "declined" in _observation_feedback([obs], "json")
        assert obs.data.get("returncode") is None
    else:
        assert obs.ok and obs.data["returncode"] == 0
        assert obs.data["requested_command"] == COMMAND
        assert not policy.has_execution_approval(context, task, "run_tests", args)
        assert not policy.has_execution_approval(context, task, "run_command", {**args, "timeout_seconds": 10})
        assert not policy.has_execution_approval(context, {**task, "task_id": "other"}, "run_command", args)
    assert context.policy == original


def test_unsafe_real_redirect_is_pending_and_never_executed(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    request = action("echo blocked>../outside")
    pending = gateway.permission_policy.create_policy_decision_if_needed(action=request, task=task, context=context)
    assert pending and "redirect" in pending["metadata"]["denial"]
    assert pending["metadata"]["execution_request"]["args"] == request["tool_calls"][0]["args"]
    assert not (tmp_path.parent / "outside").exists()
    assert not (context.run_dir / "tool_calls.jsonl").exists()


def test_native_nested_shell_literal_uses_its_own_quoting_rules(tmp_path):
    command = ('powershell -NoProfile -NonInteractive -Command "Write-Output \'value > (1)\'"'
               if sys.platform == "win32" else "sh -c 'printf \"%s\\n\" \"value > (1)\"'")
    task, _, context, gateway = setup_run(tmp_path)
    assert gateway.permission_policy.create_policy_decision_if_needed(
        action=action(command), task=task, context=context) is None
    observed = execute_tool_calls(gateway, action(command)["tool_calls"], task, context)[0]
    assert observed.ok and observed.data["stdout"].strip().splitlines()[-1] == "value > (1)"
    assert observed.data["requested_command"] == command
