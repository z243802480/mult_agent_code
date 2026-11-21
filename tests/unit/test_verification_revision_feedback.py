"""Rejection facts reach the model without changing revision eligibility."""
from copy import deepcopy
import hashlib
import json
import sys

import pytest

from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.storage.jsonl_store import JsonlStore
from tests.unit.test_verification_references import setup_run, execute, reference_args
from tests.unit.test_verification_revision import ARGS, NEW, REQUIRED, records

PROBE = f'"{sys.executable}" -c "assert 3 == 3"'


def revise(task, context, gateway, args):
    return gateway.run_tool_calls([{"tool_name": "revise_verification", "args": args}],
                                  task, context, stop_on_failure=False)[0]


def test_stale_rejection_identifies_actual_invalidator_and_model_can_recheck(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    probe = execute(task, context, gateway, command=PROBE)
    assert probe.ok and probe.data["workspace_changes"] == {"created": [], "modified": [], "deleted": []}
    before = (context.run_dir / "task_plan.json").read_bytes()
    rejected = revise(task, context, gateway, args)
    assert not rejected.ok and rejected.status == "denied" and "stale" in rejected.error
    facts = rejected.data["verification_rejection"]
    assert facts["reason_code"] == "replacement_evidence_stale"
    assert facts["failed_execution"]["tool_call_id"] == args["failed_tool_call_id"]
    assert facts["passed_execution"]["tool_call_id"] == args["passed_tool_call_id"]
    assert facts["invalidating_execution"]["tool_call_id"] == probe.harness_observation.data["tool_call_id"]
    assert facts["invalidating_execution"]["dispatch_state"] == "dispatched"
    assert facts["invalidating_execution"]["command_sha256"] == hashlib.sha256(PROBE.encode()).hexdigest()
    assert facts["requirement_coverage"] == "unassessed"
    assert (context.run_dir / "task_plan.json").read_bytes() == before
    feedback = _observation_feedback([rejected.harness_observation], "json", include_payloads=True)
    assert facts["invalidating_execution"]["tool_call_id"] in feedback
    durable = records(context)[-1]["observation"]["data"]["verification_rejection"]
    assert durable == facts
    fresh = execute(task, context, gateway, command=NEW)
    args["passed_tool_call_id"] = fresh.harness_observation.data["tool_call_id"]
    accepted = revise(task, context, gateway, args)
    assert accepted.ok, accepted.error
    assert task["validation_commands"] == [NEW, REQUIRED]
    assert task["verification_policy"]["method_revisions"][-1]["reference_binding"]["passed_tool_call_id"] == args["passed_tool_call_id"]
    assert json.loads((context.run_dir / "goal_spec.json").read_text(encoding="utf8"))["original_goal"] == goal["original_goal"]


@pytest.mark.parametrize("case", ["missing", "ambiguous"])
def test_unresolved_reference_lists_real_unique_current_evidence_without_guessing(tmp_path, case):
    task, _, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    if case == "missing":
        args["failed_tool_call_id"] = "toolcall-invented"
    else:
        rows = records(context)
        rows.append(deepcopy(rows[0]))
        JsonlStore(context.validator).rewrite_all(context.run_dir / "tool_observations.jsonl", rows, "tool_observation")
    before = (context.run_dir / "task_plan.json").read_bytes()
    denied = revise(task, context, gateway, args)
    assert not denied.ok
    facts = denied.data["verification_rejection"]
    assert facts["reason_code"] == "execution_reference_unresolved"
    assert facts["resolution"] == case
    evidence = facts["available_executions"]
    actual = records(context)[:-1]
    for row in evidence["observations"]:
        matches = [o for o in actual if o["tool_call_id"] == row["tool_call_id"]]
        assert len(matches) == 1
        assert matches[0]["task_id"] == task["task_id"] and matches[0]["run_id"] == context.run_id
    assert args["passed_tool_call_id"] in {o["tool_call_id"] for o in evidence["observations"]}
    assert (context.run_dir / "task_plan.json").read_bytes() == before
    assert facts["requirement_coverage"] == "unassessed"


@pytest.mark.parametrize("foreign", ["run", "task", "inconsistent"])
def test_feedback_excludes_foreign_or_inconsistent_records(tmp_path, foreign):
    task, _, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    rows = records(context)
    copied = deepcopy(rows[-1])
    copied["tool_call_id"] = "foreign-call"
    copied["observation_id"] = "foreign-observation"
    if foreign == "run":
        copied["run_id"] = "foreign-run"
    elif foreign == "task":
        copied["task_id"] = "foreign-task"
    else:
        copied["observation"]["ok"] = False
    rows.append(copied)
    JsonlStore(context.validator).rewrite_all(context.run_dir / "tool_observations.jsonl", rows, "tool_observation")
    args["failed_tool_call_id"] = "not-a-call"
    facts = revise(task, context, gateway, args).data["verification_rejection"]
    assert "foreign-call" not in json.dumps(facts)
    assert len(facts["available_executions"]["observations"]) == 2


def test_feedback_is_bounded_and_does_not_include_raw_outputs(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    args = reference_args(task, context, gateway)
    for _ in range(10):
        execute(task, context, gateway, command=NEW)
    args["failed_tool_call_id"] = "unknown"
    facts = revise(task, context, gateway, args).data["verification_rejection"]
    evidence = facts["available_executions"]
    assert evidence["truncated"] is True and evidence["total"] == 12
    assert len(evidence["observations"]) == 8
    assert evidence["source"] == "current_run_task_ledger"
    assert all(len(o["command_excerpt"]) <= 240 for o in evidence["observations"])
    assert not any(k in json.dumps(facts) for k in ['"stdout"', '"stderr"', '"payload"'])


def test_protected_method_denial_does_not_become_a_feedback_grant(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    reference_args(task, context, gateway)
    before = (context.run_dir / "task_plan.json").read_bytes()
    result = revise(task, context, gateway, {**ARGS, "original_command": REQUIRED})
    assert not result.ok and "provenance" in result.error
    assert "verification_rejection" not in result.data
    assert before == (context.run_dir / "task_plan.json").read_bytes()
