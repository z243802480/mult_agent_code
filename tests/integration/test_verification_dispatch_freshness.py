"""A refused action is not an execution; unknown/entered actions remain conservative."""

from copy import deepcopy

import pytest

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.model_driven_turn import _observation_feedback, execute_tool_calls
from asteria_runtime.core.task_verification import (
    commands_needing_execution, declared_observations, readbacks_needing_execution,
)
from asteria_runtime.core.verification_revision import revise_method
from asteria_runtime.storage.json_store import JsonStore
from tests.unit.test_verification_revision import (
    ARGS, NEW, REQUIRED, records, run_commands, setup_run,
)


def denied_write(task, context, gateway):
    task["edit_boundary"] = {"mode": "restricted", "paths": ["answer.txt"]}
    call = {"tool_name": "write_file", "args": {"path": "outside.txt", "content": "forbidden"}}
    return execute_tool_calls(gateway, [call], task, context)[0]


def test_real_pre_dispatch_denial_preserves_revision_evidence_and_feedback(tmp_path, monkeypatch):
    task, goal, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)
    before = deepcopy(task)
    original_call = gateway.registry.call
    calls = []

    def spy(*args, **kwargs):
        calls.append(args[0])
        return original_call(*args, **kwargs)

    monkeypatch.setattr(gateway.registry, "call", spy)
    failure = denied_write(task, context, gateway)
    assert calls == [] and not (tmp_path / "outside.txt").exists()
    assert not failure.ok and failure.dispatch_state == "not_dispatched"
    durable = records(context)[-1]
    assert durable["observation"]["dispatch_state"] == "not_dispatched"
    assert failure.data["tool_call_id"] == durable["tool_call_id"]
    assert '"dispatch_state":"not_dispatched"' in _observation_feedback([failure], "json")
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": ARGS}],
                                    task, context, stop_on_failure=False)[0]
    assert result.ok, result.error
    assert task["validation_commands"] == [NEW, REQUIRED]
    for key in ("acceptance", "completion_contract", "write_scope", "allowed_tools"):
        assert task[key] == before[key]
    assert not (tmp_path / "outside.txt").exists()
    assert records(context)[-2] == durable
    assert goal == JsonStore(context.validator).read(context.run_dir / "goal_spec.json", "goal_spec")


@pytest.mark.parametrize("state,ok,changed,stale", [
    ("not_dispatched", False, False, False),
    ("dispatched", False, False, True),
    ("unknown", False, False, True),
    ("not_dispatched", True, False, True),
    ("not_dispatched", False, True, True),
])
def test_freshness_requires_explicit_consistent_non_dispatch(state, ok, changed, stale):
    task = {"validation_commands": ["check"], "task_kind": "diagnostic", "write_scope": [],
            "verification_policy": {"command_source": "planner_task", "readback_paths": ["a.txt"]}}
    good = ToolObservation("run_tests", True, "check", "success", data={"command": "check"})
    read = ToolObservation("read_file", True, "read", "success", data={"path": "a.txt"})
    action = ToolObservation("apply_patch", ok, "denied", "denied",
                             dispatch_state=state, data={"changed_files": ["a.txt"]} if changed else {})
    observations = [good, read, action]
    assert bool(commands_needing_execution(task, observations)) == stale
    assert bool(readbacks_needing_execution(task, observations)) == stale


def test_legacy_denial_without_dispatch_proof_still_blocks_revision(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)
    old = records(context)
    old.append({"task_id": task["task_id"], "observation": {
        "tool_name": "apply_patch", "ok": False, "summary": "policy denied", "status": "denied"}})
    project = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")
    with pytest.raises(PermissionError, match="stale"):
        revise_method(task, goal, (tmp_path / "AGENTS.md").read_text(), project["commands"], old, **ARGS)


def test_tool_that_writes_then_raises_permission_error_still_invalidates(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)

    class WritesThenDenies:
        name = "apply_patch"

        def run(self, context, **kwargs):
            (context.root / "answer.txt").write_text("changed")
            raise PermissionError("denied after an effect")

    gateway.registry._tools["apply_patch"] = WritesThenDenies()
    result = gateway.run_tool_calls([{"tool_name": "apply_patch", "args": {
        "patch": "--- /dev/null\n+++ b/answer.txt\n@@ -0,0 +1 @@\n+changed\n"}}],
        task, context, stop_on_failure=False)[0]
    assert (tmp_path / "answer.txt").read_text() == "changed"
    assert not result.ok and result.harness_observation.dispatch_state == "dispatched"
    project = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")
    with pytest.raises(PermissionError, match="stale"):
        revise_method(task, goal, (tmp_path / "AGENTS.md").read_text(), project["commands"], records(context), **ARGS)


def test_approval_context_failure_never_enters_registry(tmp_path, monkeypatch):
    task, _, context, gateway = setup_run(tmp_path)
    def fail(*args, **kwargs):
        raise PermissionError("approval preparation refused")
    monkeypatch.setattr(type(gateway.permission_policy), "context_with_approval", fail)
    observation = execute_tool_calls(gateway, [{"tool_name": "run_tests", "args": {"command": NEW}}],
                                     task, context)[0]
    assert observation.dispatch_state == "not_dispatched" and not observation.ok
    assert records(context)[-1]["observation"]["dispatch_state"] == "not_dispatched"


def test_hook_boundary_failure_remains_unknown(tmp_path, monkeypatch):
    task, _, context, gateway = setup_run(tmp_path)
    original = type(gateway)._emit
    def fail(self, context, hook_name, *args, **kwargs):
        if hook_name == "before_tool_call":
            (context.root / "answer.txt").write_text("hook effect")
            raise PermissionError("hook failed")
        return original(self, context, hook_name, *args, **kwargs)
    monkeypatch.setattr(type(gateway), "_emit", fail)
    observation = execute_tool_calls(gateway, [{"tool_name": "run_tests", "args": {"command": NEW}}],
                                     task, context)[0]
    assert observation.dispatch_state == "unknown" and not observation.ok
    assert (tmp_path / "answer.txt").read_text() == "hook effect"


def test_rejected_required_check_remains_failed_and_cannot_satisfy_contract():
    task = {"validation_commands": ["check"], "verification_policy": {"command_source": "planner_task"}}
    denied = ToolObservation("run_tests", False, "denied", "failure",
                             dispatch_state="not_dispatched", data={"command": "check"})
    assert declared_observations(task, [denied]) == [denied]
    assert not declared_observations(task, [denied])[0].ok


def test_real_required_refusal_keeps_command_identity_and_supersedes_prior_green(tmp_path, monkeypatch):
    task, _, context, gateway = setup_run(tmp_path)
    task["validation_commands"].append(NEW)
    task["verification_policy"]["commands"].append(NEW)
    previous = run_commands(task, context, gateway)[-1].harness_observation
    def deny(*args, **kwargs):
        raise PermissionError("execution declined")
    monkeypatch.setattr(type(gateway.permission_policy), "enforce_tool_permission_profile", deny)
    rejected = execute_tool_calls(gateway, [{"tool_name": "run_tests", "args": {"command": NEW}}],
                                  task, context)[0]
    assert not rejected.ok and rejected.dispatch_state == "not_dispatched"
    durable = records(context)[-1]["observation"]
    assert durable["data"]["requested_command"] == NEW
    selected = declared_observations(task, [previous, ToolObservation(**durable)])
    assert selected[-1].data["requested_command"] == NEW and not selected[-1].ok


def test_tool_return_data_cannot_spoof_gateway_dispatch_fact(tmp_path):
    from asteria_runtime.tools.base import ToolResult
    task, _, context, gateway = setup_run(tmp_path)
    class PretendsNotToRun:
        name = "run_tests"
        def run(self, context, **kwargs):
            return ToolResult(ok=False, summary="failed", data={"dispatch_state": "not_dispatched"})
    gateway.registry._tools["run_tests"] = PretendsNotToRun()
    result = gateway.run_tool_calls([{"tool_name": "run_tests", "args": {"command": NEW}}],
                                    task, context, stop_on_failure=False)[0]
    assert result.harness_observation.dispatch_state == "dispatched"
    assert result.harness_observation.data["dispatch_state"] == "not_dispatched"
