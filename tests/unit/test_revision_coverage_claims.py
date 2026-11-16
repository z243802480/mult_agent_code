from copy import deepcopy
import sys

import pytest

from asteria_runtime.core.verification_revision import method_provenance
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError
from tests.unit.test_verification_revision import setup_run, OLD, REQUIRED


@pytest.mark.parametrize("checks_unit,unit,expected_revision", [
    (True, "items", True), (True, "wrong", False), (False, "wrong", True),
])
def test_method_execution_and_claimed_multi_condition_coverage_are_separate(
    tmp_path, checks_unit, unit, expected_revision,
):
    task, goal, context, gateway = setup_run(tmp_path)
    goal["original_goal"] = "The value must be 42 and its unit must be items. Preserve the required project check."
    task["acceptance"] = ["value is 42", "unit is items"]
    project = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")
    guidance = (tmp_path / "AGENTS.md").read_text()
    task["verification_policy"]["method_provenance"] = method_provenance(task["validation_commands"], goal, {
        "root_guidance": {"content": guidance, "truncated": False}, "project_commands": project["commands"],
    })
    store = JsonStore(context.validator)
    store.write(context.run_dir / "goal_spec.json", goal, "goal_spec")
    store.write(context.run_dir / "task_plan.json", {"schema_version": "0.1.0", "tasks": [task]}, "task_board")
    (tmp_path / "answer.py").write_text(f"VALUE = 42\nUNIT = {unit!r}\n")
    goal_bytes = (context.run_dir / "goal_spec.json").read_bytes()
    before = deepcopy(task)
    body = "from answer import VALUE, UNIT; assert VALUE == 42"
    if checks_unit:
        body += "; assert UNIT == 'items'"
    candidate = f'"{sys.executable}" -c "{body}"'
    executed = gateway.run_tool_calls([
        {"tool_name": "run_tests", "args": {"command": OLD}},
        {"tool_name": "run_tests", "args": {"command": candidate}},
    ], task, context, stop_on_failure=False)
    assert not executed[0].ok and executed[1].ok is expected_revision
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": {
        "original_command": OLD, "replacement_command": candidate,
        "reason": "The original method fails before exercising the artifact",
        "coverage": "All original conditions are preserved",  # A claim, including in the incomplete case.
    }}], task, context, stop_on_failure=False)[0]
    assert result.ok is expected_revision
    assert (context.run_dir / "goal_spec.json").read_bytes() == goal_bytes
    if expected_revision:
        revision = task["verification_policy"]["method_revisions"][-1]
        assert revision["coverage_assessment"] == {"source": "agent_statement", "runtime_verified": False}
        assert REQUIRED in task["validation_commands"]
        for key in ("acceptance", "completion_contract", "write_scope", "allowed_tools"):
            assert task[key] == before[key]
        legacy = deepcopy(task)
        del legacy["verification_policy"]["method_revisions"][-1]["coverage_assessment"]
        context.validator.validate("task", legacy)
        revision["coverage_assessment"]["runtime_verified"] = True
        with pytest.raises(SchemaValidationError):
            context.validator.validate("task", task)
