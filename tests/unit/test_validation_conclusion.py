"""Current method membership is separate from immutable execution history."""

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def task(commands=None, **changes):
    return {
        "task_id": "task-1",
        "status": "done",
        "task_kind": "verification",
        "write_scope": [],
        "validation_commands": commands or [],
        "verification_policy": {"command_source": "planner_task"},
        **changes,
    }


def row(
    index,
    command="check current",
    ok=True,
    *,
    name="run_tests",
    task_id="task-1",
    run_id="run-control",
    **data,
):
    observation = ToolObservation(
        name,
        ok,
        "Scripted execution record",
        "success" if ok else "failure",
        data={"command": command, "returncode": 0 if ok else 1, **data},
        dispatch_state="dispatched",
    ).to_dict()
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "task_id": task_id,
        "tool_call_id": f"call-{index}",
        "observation_id": f"obs-{index}",
        "tool_name": name,
        "ok": ok,
        "status": observation["status"],
        "summary": "Scripted execution record",
        "observation": observation,
        "created_at": "2026-11-23T00:00:00Z",
    }


def conclude(root, tasks, observations, *, validations=None):
    run = root / ".asteria/runs/run-control"
    validator = SchemaValidator(Path("schemas"))
    store, jsonl = JsonStore(validator), JsonlStore(validator)
    store.write(run / "task_plan.json", {"schema_version": "0.1.0", "tasks": tasks}, "task_board")
    for item in observations:
        jsonl.append(run / "tool_observations.jsonl", item, "tool_observation")
        jsonl.append(
            run / "tool_calls.jsonl",
            {
                k: item[k]
                for k in (
                    "schema_version",
                    "run_id",
                    "task_id",
                    "tool_call_id",
                    "tool_name",
                    "status",
                )
            }
            | {"input_summary": "Scripted", "output_summary": "Scripted"},
            "tool_call",
        )
    for item in validations or []:
        jsonl.append(run / "validation_results.jsonl", item, "validation_result")
    before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    result = RunCommand(root)._validation_conclusion(run)
    assert before == {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    return result


def test_replaced_failed_method_stays_in_history_not_current_results(tmp_path):
    current = task(["check current"])
    current["verification_policy"]["method_revisions"] = [
        {"original_command": "old check", "replacement_command": "check current"}
    ]
    result = conclude(tmp_path, [current], [row(1, "old check", False), row(2)])
    assert result["status"] == "passed"
    assert result["total"] == result["passed"] == 1
    assert result["history"]["failed"] == 1
    assert result["history"]["total"] == 2
    assert result["artifact_freshness"] == result["requirement_coverage"] == "unassessed"


@pytest.mark.parametrize(
    "statuses,expected", [([False, True], "passed"), ([True, False], "failed")]
)
def test_latest_required_result_does_not_double_count_retries(tmp_path, statuses, expected):
    result = conclude(
        tmp_path, [task(["check current"])], [row(i, ok=ok) for i, ok in enumerate(statuses)]
    )
    assert result["status"] == expected and result["total"] == 1
    assert result["history"]["failed"] == 1


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "write_after",
        "other_task",
        "other_run",
        "boolean_exit",
        "ambiguous",
        "inconsistent",
    ],
)
def test_missing_stale_or_unqualified_current_evidence_never_passes(tmp_path, case):
    observations = [row(1)]
    if case == "missing":
        observations = [row(1, "unrelated")]
    elif case == "write_after":
        observations.append(row(2, "", name="write_file"))
    elif case == "other_task":
        observations[0]["task_id"] = "other-task"
    elif case == "other_run":
        observations[0]["run_id"] = "other-run"
    elif case == "boolean_exit":
        observations[0]["observation"]["data"]["returncode"] = False
    elif case == "ambiguous":
        observations.append(json.loads(json.dumps(observations[0])))
    elif case == "inconsistent":
        observations[0]["ok"] = False
    result = conclude(tmp_path, [task(["check current"])], observations)
    assert result["status"] != "passed"
    assert result["scope"] == "current_declared_methods_at_recorded_task_execution"


def test_unregistered_green_probe_cannot_mask_required_failure(tmp_path):
    result = conclude(tmp_path, [task(["check current"])], [row(1, "unrelated"), row(2, ok=False)])
    assert result["status"] == "failed" and result["failed"] == 1


def test_discarded_failure_is_historical_but_missing_live_contract_is_unknown(tmp_path):
    old = task(["old"], task_id="old", status="discarded")
    result = conclude(
        tmp_path, [old, task(["check current"])], [row(1, "old", False, task_id="old"), row(2)]
    )
    assert result["status"] == "passed" and result["history"]["failed"] == 1


def test_mixed_missing_contract_does_not_certify_green(tmp_path):
    result = conclude(
        tmp_path, [task(["check current"]), {"task_id": "other", "status": "done"}], [row(1)]
    )
    assert result["status"] == "not_recorded"
    assert result["unassessed_task_ids"] == ["other"]


@pytest.mark.parametrize(
    "case",
    ["duplicate_task", "mismatched_call", "policy_mismatch", "invalid_data", "invalid_commands"],
)
def test_ambiguous_or_inconsistent_contract_sources_remain_unassessed(tmp_path, case):
    current = task(["check current"])
    tasks, observations = [current], [row(1)]
    if case == "duplicate_task":
        tasks.append(task(["check current"]))
    elif case == "mismatched_call":
        observations[0]["observation"]["tool_name"] = "read_file"
    elif case == "policy_mismatch":
        current["verification_policy"]["commands"] = ["another method"]
    elif case == "invalid_data":
        observations[0]["observation"]["data"] = ["not execution data"]
    else:
        current["validation_commands"] = "check current"
    result = conclude(tmp_path, tasks, observations)
    assert result["status"] == "not_recorded"
    assert result["unassessed_task_ids"] == ["task-1"]


@pytest.mark.parametrize("paths", [["README.md"], []])
def test_readback_contract_uses_existing_rules_and_empty_is_not_green(tmp_path, paths):
    current = task()
    current["verification_policy"]["readback_paths"] = paths
    result = conclude(
        tmp_path,
        [current],
        [row(1, "probe", False), row(2, "", name="read_file", path="README.md")],
    )
    assert result["status"] == ("passed" if paths else "not_recorded")
    assert result["history"]["failed"] == 1


def test_legacy_uncontracted_history_remains_explicitly_historical(tmp_path):
    result = conclude(tmp_path, [{"task_id": "task-1", "status": "done"}], [row(1)])
    assert result["status"] == "passed" and result["scope"] == "historical_records_only"
    assert "Historical" in result["summary"]


def test_real_gateway_revision_does_not_waive_the_separate_required_check(tmp_path):
    from tests.unit.test_verification_revision import ARGS, run_commands, setup_run

    current, _goal, context, gateway = setup_run(tmp_path)
    run_commands(current, context, gateway)
    revision = gateway.run_tool_calls(
        [{"tool_name": "revise_verification", "args": ARGS}],
        current,
        context,
        stop_on_failure=False,
    )[0]
    assert revision.ok
    run = context.run_dir
    before = (run / "tool_observations.jsonl").read_bytes()
    result = RunCommand(tmp_path)._validation_conclusion(run)
    assert result["status"] == "failed"
    assert result["total"] == 2 and result["passed"] == result["failed"] == 1
    assert result["history"]["failed"] == 1
    assert (run / "tool_observations.jsonl").read_bytes() == before
