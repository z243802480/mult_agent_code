from copy import deepcopy
from pathlib import Path

import pytest

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_consent_is_exact_task_action_and_arguments_not_global_permission(tmp_path):
    validator = SchemaValidator(Path("schemas"))
    context = RuntimeContext(tmp_path, "run-permission", {"permissions": {"allow_shell": False}}, validator,
                             run_dir_override=tmp_path)
    task = {"task_id": "task-1", "allowed_tools": ["request_execution_permission", "run_command"]}
    args = {"command": "echo consent-test", "timeout_seconds": 10}
    request = {"tool_name": "request_execution_permission", "args": {
        "tool_name": "run_command", "args": args, "reason": "Need this precise action",
    }}
    policy = ToolPermissionPolicy(tmp_path, validator)
    original = deepcopy(context.policy)
    decision = policy.create_policy_decision_if_needed(action={"tool_calls": [request]}, task=task, context=context)
    assert decision is not None
    assert not policy.has_execution_approval(context, task, "run_command", args)
    assert policy.create_policy_decision_if_needed(action={"tool_calls": [request]}, task=task,
                                                  context=context) == decision
    decision.update(status="resolved", selected_option_id="approve_once")
    ledger = JsonlStore(validator)
    ledger.rewrite_all(tmp_path / "decisions.jsonl", [decision], "decision_point")
    assert policy.has_execution_approval(context, task, "run_command", args)
    assert not policy.has_execution_approval(context, {**task, "task_id": "task-2"}, "run_command", args)
    assert not policy.has_execution_approval(context, task, "run_tests", args)
    assert not policy.has_execution_approval(context, task, "run_command", {**args, "timeout_seconds": 11})
    assert not policy.has_execution_approval(context, task, "run_command", {**args, "command": "echo different"})
    granted = policy.context_with_approval(context, task, "run_command", args)
    assert granted.policy["permissions"]["allow_shell"]
    assert context.policy == original
    decision.update(selected_option_id="skip")
    ledger.rewrite_all(tmp_path / "decisions.jsonl", [decision], "decision_point")
    assert policy.create_policy_decision_if_needed(action={"tool_calls": [request]}, task=task, context=context) is None
    with pytest.raises(PermissionError, match="declined"):
        policy.enforce_tool_permission_profile(task, "run_command", args, context)


def test_unlisted_execution_cannot_request_a_capability_grant(tmp_path):
    validator = SchemaValidator(Path("schemas"))
    context = RuntimeContext(tmp_path, "run-permission", {}, validator, run_dir_override=tmp_path)
    request = {"tool_name": "request_execution_permission", "args": {
        "tool_name": "run_command", "args": {"command": "echo forbidden"}, "reason": "request",
    }}
    assert ToolPermissionPolicy(tmp_path, validator).create_policy_decision_if_needed(
        action={"tool_calls": [request]}, task={"task_id": "task-1", "allowed_tools": []}, context=context,
    ) is None
    assert not (tmp_path / "decisions.jsonl").exists()
