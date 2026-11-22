"""A persisted scan is useful only when its scope reaches the model unchanged."""
from copy import deepcopy
from dataclasses import replace
import json
import sys

import pytest

from asteria_runtime.core.agent_harness import observation_from_tool_result
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.core.workspace_snapshot import observation_coverage
from asteria_runtime.tools.base import ToolResult
from tests.unit.test_model_driven_turn import FakeModelClient, FakeToolRunner, FakeToolResult, _json_resp, _run


def facts(scan="stat_only"):
    return {"tool_call_id": "call-source", "returncode": 0, "workspace_scan": scan,
            "workspace_scan_coverage": observation_coverage(),
            "workspace_changes": None if scan == "unavailable" else {"created": [], "modified": [], "deleted": []}}


def receipt(feedback):
    return json.loads(next(line.split("Execution receipt: ", 1)[1]
                           for line in feedback.splitlines() if line.startswith("Execution receipt: ")))


@pytest.mark.parametrize("transport", ["json", "tool_use"])
@pytest.mark.parametrize("case", ["quiet", "failed", "unavailable"])
def test_scan_scope_and_permission_facts_reach_model_even_without_command_output(transport, case):
    data = facts("unavailable" if case == "unavailable" else "stat_only")
    if case == "failed":
        data.update(returncode=1, stderr="original failure")
    original = deepcopy(data)
    obs = observation_from_tool_result(tool_name="run_tests", result=ToolResult(
        ok=case != "failed", summary="Command exited", data=data,
    ))
    view = receipt(_observation_feedback([obs], transport))["workspace_observation"]
    assert view["scan"] == data["workspace_scan"]
    if data["workspace_changes"] is None:
        assert view["changes"] is None
    else:
        assert {key: value["items"] for key, value in view["changes"].items()} == data["workspace_changes"]
    assert view["coverage"]["exclusions_grant_permission"] is False
    assert "__pycache__" in view["coverage"]["excluded_directories"]["items"]
    assert view["coverage"]["limitations"]["items"] == original["workspace_scan_coverage"]["limitations"]
    assert view["authorization"] == "not_granted_by_observation"
    assert data == original and obs.data == original


def test_real_gateway_observation_retains_raw_effects_and_exposes_bounded_scan_scope(tmp_path):
    from tests.unit.test_verification_references import setup_run, execute
    from tests.unit.test_verification_revision import records
    task, _, context, gateway = setup_run(tmp_path)
    code = "from pathlib import Path; Path('.ruff_cache').mkdir(); Path('.ruff_cache/state').write_text('cache'); Path('side.bin').write_text('new'); print('OBSERVED')"
    result = execute(task, context, gateway, command=f'"{sys.executable}" -c "{code}"')
    assert result.ok
    row = records(context)[-1]
    assert row["observation"]["data"]["workspace_changes"]["created"] == ["side.bin"]
    feedback = _observation_feedback([result.harness_observation], "json")
    scan = receipt(feedback)["workspace_observation"]
    assert scan["changes"]["created"]["items"] == ["side.bin"]
    assert ".ruff_cache" in scan["coverage"]["excluded_directories"]["items"]
    assert "OBSERVED" in feedback and scan["authorization"] == "not_granted_by_observation"


def test_large_output_and_effects_cannot_erase_scan_limits_or_overflow_receipt():
    data = facts()
    data["stdout"] = "LARGE_OUTPUT" * 2000
    data["workspace_changes"]["created"] = [str(i) + "x" * 500 for i in range(80)]
    obs = observation_from_tool_result(tool_name="run_command", result=ToolResult(ok=True, summary="s", data=data))
    feedback = _observation_feedback([obs], "json")
    scan = receipt(feedback)["workspace_observation"]
    changed = scan["changes"]["created"]
    assert len(changed["items"]) == 8 and changed["omitted_items"] == 72 and changed["truncated_items"] == 8
    assert scan["coverage"]["max_scan_files"] == 5000
    assert len(feedback) < 12_000 and obs.data["workspace_changes"] == data["workspace_changes"]


def test_old_or_absent_scan_data_does_not_become_an_effect_free_claim():
    obs = observation_from_tool_result(tool_name="run_command", result=ToolResult(
        ok=True, summary="s", data={"returncode": 0, "stdout": "legacy output", "tool_call_id": "old"},
    ))
    assert receipt(_observation_feedback([obs], "json")) == {"tool_call_id": "old", "returncode": 0}
    unknown = replace(obs, data={**obs.data, "workspace_scan": "unavailable", "workspace_changes": None})
    assert receipt(_observation_feedback([unknown], "json"))["workspace_observation"]["changes"] is None


def test_receipt_survives_history_compression_and_reaches_next_real_request_assembly():
    first = facts()
    first["stdout"] = "old-output" * 500
    second = facts()
    second["tool_call_id"] = "recent-call"
    second["stdout"] = "new-output" * 500
    model = FakeModelClient([_json_resp("scan", [{"tool_name": "run_tests", "args": {"command": "first"}}]),
                             _json_resp("check", [{"tool_name": "run_tests", "args": {"command": "second"}}]),
                             _json_resp("done", done=True)])
    tools = FakeToolRunner([[FakeToolResult(data=first)], [FakeToolResult(data=second)]])
    result = _run(model, tools, transport="json", history_char_budget=8000, keep_recent_observation_payloads=1)
    assert result.status == "completed"
    feedback = [m.text() for m in model.requests[-1].messages if m.text().startswith("Tool results")]
    assert "elided" in feedback[0] and "old-output" not in feedback[0]
    assert receipt(feedback[0])["workspace_observation"]["coverage"]["exclusions_grant_permission"] is False
    assert receipt(feedback[1])["workspace_observation"]["scan"] == "stat_only"
