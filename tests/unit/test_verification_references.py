from copy import deepcopy
from dataclasses import replace
import sys

import pytest

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.core.verification_references import verification_methods
from asteria_runtime.core.verification_revision import method_provenance
from asteria_runtime.core.tool_batch_result import ToolBatchError
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError
from tests.unit.test_verification_revision import setup_run as setup_revision_run, records, OLD, NEW, REQUIRED, ARGS


def setup_run(tmp_path):
    task, goal, context, gateway = setup_revision_run(tmp_path)
    JsonStore(context.validator).write(context.run_dir / "run.json", {
        "schema_version": "0.1.0", "run_id": context.run_id, "goal_id": goal["goal_id"],
        "status": "running", "started_at": "2026-11-16T00:00:00Z", "current_phase": "EXECUTE",
    }, "run")
    return task, goal, context, gateway


def persist(task, context):
    JsonStore(context.validator).write(context.run_dir / "task_plan.json",
                                     {"schema_version": "0.1.0", "tasks": [task]}, "task_board")


def execute(task, context, gateway, **args):
    return gateway.run_tool_calls([{"tool_name": "run_tests", "args": args}], task, context, stop_on_failure=False)[0]


def reference_args(task, context, gateway):
    reference = verification_methods(task, context)[0]["verification_ref"]
    failed = execute(task, context, gateway, verification_ref=reference)
    passed = execute(task, context, gateway, command=NEW)
    assert not failed.ok and passed.ok
    return {"original_verification_ref": reference,
            "failed_tool_call_id": failed.harness_observation.data["tool_call_id"],
            "passed_tool_call_id": passed.harness_observation.data["tool_call_id"],
            "reason": ARGS["reason"], "coverage": ARGS["coverage"]}


def test_exact_reference_execution_receipts_and_revision_keep_requirements_and_refresh_references(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    before = deepcopy(task)
    args = reference_args(task, context, gateway)
    rows = records(context)
    assert rows[0]["observation"]["data"]["requested_command"] == OLD
    assert rows[0]["observation"]["data"]["verification_ref"] == args["original_verification_ref"]
    feedback = _observation_feedback([ToolObservation(**r["observation"]) for r in rows], "json", include_payloads=False)
    assert args["failed_tool_call_id"] in feedback and args["passed_tool_call_id"] in feedback
    assert args["original_verification_ref"] in feedback and '"returncode":1' in feedback
    prefix = (context.run_dir / "tool_observations.jsonl").read_bytes()
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": args}], task, context,
                                    stop_on_failure=False)[0]
    assert result.ok, result.error
    revision = task["verification_policy"]["method_revisions"][-1]
    assert revision["reference_binding"] == {key: args[key] for key in (
        "original_verification_ref", "failed_tool_call_id", "passed_tool_call_id")}
    assert revision["failed_observation_id"] == rows[0]["observation_id"]
    assert revision["passed_observation_id"] == rows[1]["observation_id"]
    assert task["validation_commands"] == [NEW, REQUIRED]
    assert result.data["verification_methods"] == verification_methods(task, context)
    assert result.data["verification_methods"][0]["verification_ref"] in result.harness_observation.payload
    assert (context.run_dir / "tool_observations.jsonl").read_bytes().startswith(prefix)
    for key in ("acceptance", "completion_contract", "allowed_tools", "write_scope"):
        assert task[key] == before[key]
    saved = JsonStore(context.validator).read(context.run_dir / "goal_spec.json", "goal_spec")
    assert saved == goal
    with pytest.raises(ToolBatchError, match="Unknown or stale"):
        execute(task, context, gateway, verification_ref=args["original_verification_ref"])
    assert execute(task, context, gateway, verification_ref=verification_methods(task, context)[0]["verification_ref"]).ok


def test_reference_never_repairs_or_normalizes_broken_shell_quotes(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    broken = f'"{sys.executable}" -c "raise RuntimeError("unescaped quoted method")"'
    task["validation_commands"] = [broken, REQUIRED]
    policy = task["verification_policy"]
    policy["commands"] = list(task["validation_commands"])
    project = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")
    policy["method_provenance"] = method_provenance(policy["commands"], goal, {
        "root_guidance": {"content": (tmp_path / "AGENTS.md").read_text(), "truncated": False},
        "project_commands": project["commands"],
    })
    persist(task, context)
    ref = verification_methods(task, context)[0]["verification_ref"]
    result = execute(task, context, gateway, verification_ref=ref)
    assert not result.ok and result.data["returncode"] != 0
    assert result.data["requested_command"] == broken  # No quote or shell transformation.


@pytest.mark.parametrize("case", ["unknown", "other_run", "other_workspace", "other_task", "old_version", "terminal", "cancelled", "mixed", "revoked_tool", "duplicate_task"])
def test_reference_execution_rejects_wrong_binding_before_process(tmp_path, case):
    task, _, context, gateway = setup_run(tmp_path)
    ref = verification_methods(task, context)[0]["verification_ref"]
    args = {"verification_ref": ref}
    if case == "unknown":
        args["verification_ref"] = "verification-forged"
    elif case == "other_run":
        args["verification_ref"] = verification_methods(task, replace(context, run_id="other-run"))[0]["verification_ref"]
    elif case == "other_workspace":
        foreign = replace(context, run_dir_override=tmp_path.parent / "different-workspace/runs/run-1")
        args["verification_ref"] = verification_methods(task, foreign)[0]["verification_ref"]
    elif case == "other_task":
        args["verification_ref"] = verification_methods({**task, "task_id": "other-task"}, context)[0]["verification_ref"]
    elif case == "old_version":
        task["verification_policy"]["method_provenance"]["goal_sha256"] = "changed"
    elif case == "terminal":
        task["status"] = "done"
    elif case == "cancelled":
        store = JsonStore(context.validator)
        run = store.read(context.run_dir / "run.json", "run")
        run["status"] = "cancelled"
        store.write(context.run_dir / "run.json", run, "run")
    elif case == "mixed":
        args["command"] = NEW
    elif case == "revoked_tool":
        fresh = deepcopy(task)
        fresh["allowed_tools"].remove("run_tests")
        persist(fresh, context)
    elif case == "duplicate_task":
        JsonStore(context.validator).write(context.run_dir / "task_plan.json",
            {"schema_version": "0.1.0", "tasks": [task, task]}, "task_board")
    if case in {"old_version", "terminal"}:
        persist(task, context)
    with pytest.raises(ToolBatchError):
        execute(task, context, gateway, **args)
    row = records(context)[-1]
    assert not row["ok"] and row["observation"]["data"].get("returncode") is None
    assert not row["observation"]["data"].get("stdout")


@pytest.mark.parametrize("case", ["forged_failure", "other_task", "other_run", "duplicate", "stale_failure", "stale_pass", "mixed", "protected", "goal_changed", "side_effect"])
def test_reference_revision_keeps_existing_authority_and_evidence_guards(tmp_path, case):
    task, _, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    rows = records(context)
    if case == "forged_failure":
        args["failed_tool_call_id"] = "forged"
    elif case in {"other_task", "other_run", "duplicate", "side_effect"}:
        if case == "other_task":
            rows[1]["task_id"] = "other"
        elif case == "other_run":
            rows[1]["run_id"] = "other-run"
        elif case == "duplicate":
            rows.append(deepcopy(rows[1]))
        else:
            rows[1]["observation"]["data"]["workspace_changes"]["created"] = ["extra.txt"]
        from asteria_runtime.storage.jsonl_store import JsonlStore
        JsonlStore(context.validator).rewrite_all(context.run_dir / "tool_observations.jsonl", rows, "tool_observation")
    elif case in {"stale_failure", "stale_pass"}:
        execute(task, context, gateway, command=OLD if case == "stale_failure" else NEW)
    elif case == "mixed":
        args["original_command"] = OLD
    elif case == "protected":
        protected = verification_methods(task, context)[1]["verification_ref"]
        failed = execute(task, context, gateway, verification_ref=protected)
        passed = execute(task, context, gateway, command=NEW)
        args.update(original_verification_ref=protected,
                    failed_tool_call_id=failed.harness_observation.data["tool_call_id"],
                    passed_tool_call_id=passed.harness_observation.data["tool_call_id"])
    elif case == "goal_changed":
        store = JsonStore(context.validator)
        goal = store.read(context.run_dir / "goal_spec.json", "goal_spec")
        goal["constraints"].append("new requirement")
        store.write(context.run_dir / "goal_spec.json", goal, "goal_spec")
    before = (context.run_dir / "task_plan.json").read_bytes()
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": args}], task, context,
                                    stop_on_failure=False)[0]
    assert not result.ok
    assert (context.run_dir / "task_plan.json").read_bytes() == before


def test_reference_approval_targets_exact_resolved_command_and_never_grants_on_invalid_ref(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    context.policy["permissions"]["allow_shell"] = False
    ref = verification_methods(task, context)[0]["verification_ref"]
    action = {"tool_calls": [{"tool_name": "run_tests", "args": {"verification_ref": ref}}]}
    policy = gateway.permission_policy
    decision = policy.create_policy_decision_if_needed(action=action, task=task, context=context)
    assert decision is not None
    assert policy.execution_decision(context, task, "run_tests", {"command": OLD}) is not None
    invalid = {"tool_calls": [{"tool_name": "run_tests", "args": {"verification_ref": "forged"}}]}
    assert policy.create_policy_decision_if_needed(action=invalid, task=task, context=context) is None
    denied = execute(task, context, gateway, verification_ref=ref)
    assert not denied.ok and denied.status == "denied"
    assert context.policy["permissions"]["allow_shell"] is False


def test_exact_approved_reference_execution_does_not_grant_other_args_or_global_permission(tmp_path):
    from asteria_runtime.storage.jsonl_store import JsonlStore
    task, _, context, gateway = setup_run(tmp_path)
    context.policy["permissions"]["allow_shell"] = False
    ref = verification_methods(task, context)[0]["verification_ref"]
    action = {"tool_calls": [{"tool_name": "run_tests", "args": {"verification_ref": ref}}]}
    decision = gateway.permission_policy.create_policy_decision_if_needed(action=action, task=task, context=context)
    decision.update(status="resolved", selected_option_id="approve_once")
    JsonlStore(context.validator).rewrite_all(context.run_dir / "decisions.jsonl", [decision], "decision_point")
    allowed = execute(task, context, gateway, verification_ref=ref)
    assert allowed.harness_observation.status == "failure" and allowed.data["returncode"] != 0  # Executed, not denied.
    changed = execute(task, context, gateway, verification_ref=ref, timeout_seconds=11)
    assert changed.status == "denied" and changed.data.get("returncode") is None
    assert context.policy["permissions"]["allow_shell"] is False


def test_schema_rejects_partial_reference_binding_in_durable_revision(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    assert gateway.run_tool_calls([{"tool_name": "revise_verification", "args": args}], task, context,
                                  stop_on_failure=False)[0].ok
    corrupt = deepcopy(task)
    corrupt["verification_policy"]["method_revisions"][-1]["reference_binding"].pop("passed_tool_call_id")
    with pytest.raises(SchemaValidationError):
        context.validator.validate("task", corrupt)
