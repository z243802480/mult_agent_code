"""Method membership and successful execution never certify semantic coverage."""
import json
import sys

import pytest

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.core.tool_batch_result import ToolBatchError
from asteria_runtime.core.verification_references import verification_methods
from asteria_runtime.core.verification_revision import method_provenance
from tests.unit.test_verification_references import setup_run, execute, persist
from tests.unit.test_verification_revision import OLD, NEW, REQUIRED, records


@pytest.mark.parametrize("by_reference", [False, True])
def test_executed_registered_failure_has_same_method_receipt_for_both_entry_forms(tmp_path, by_reference):
    task, _, context, gateway = setup_run(tmp_path)
    method = verification_methods(task, context)[0]
    result = execute(task, context, gateway, **({"verification_ref": method["verification_ref"]}
                                             if by_reference else {"command": OLD}))
    assert not result.ok and result.data["returncode"] != 0
    receipt = result.harness_observation.data["verification_method"]
    assert receipt["verification_ref"] == method["verification_ref"]
    assert receipt["revision_eligibility"] == "planner_candidate_recheck_required"
    assert receipt["method_relation"] == "current_declared_task_method"
    assert receipt["requirement_coverage"] == "unassessed"
    assert result.data["requested_command"] == OLD
    row = records(context)[-1]
    assert row["observation"]["data"]["verification_method"] == receipt
    feedback = _observation_feedback([ToolObservation(**row["observation"])], "json", include_payloads=False)
    assert json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) in feedback


def test_unregistered_success_is_not_a_replacement_or_a_coverage_verdict(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    before = (context.run_dir / "task_plan.json").read_bytes()
    result = execute(task, context, gateway, command=NEW)
    receipt = result.harness_observation.data["verification_method"]
    assert result.ok and receipt == {"method_relation": "unregistered_or_unknown",
                                    "requirement_coverage": "unassessed"}
    assert (context.run_dir / "task_plan.json").read_bytes() == before


def test_refused_reference_is_not_reported_as_an_executed_method(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    with pytest.raises(ToolBatchError):
        execute(task, context, gateway, verification_ref="unknown")
    data = records(context)[-1]["observation"]["data"]
    assert data.get("returncode") is None and "verification_method" not in data


@pytest.mark.parametrize("body,valid,naive_passes", [
    ("return 42", True, True), ("return 6 * 7", True, False),
    ("return 43  # return 42", False, True),
])
def test_actual_methods_discriminate_valid_alternatives_and_real_defect_without_certifying_coverage(
    tmp_path, body, valid, naive_passes,
):
    task, goal, context, gateway = setup_run(tmp_path)
    source = f"def answer():\n    {body}\n"
    (tmp_path / "answer.py").write_text(source)
    naive = f'"{sys.executable}" -c "from pathlib import Path; assert \'return 42\' in Path(\'answer.py\').read_text()"'
    actual = f'"{sys.executable}" -c "from answer import answer; assert answer() == 42"'
    task["validation_commands"] = [naive, REQUIRED]
    task["verification_policy"]["commands"] = list(task["validation_commands"])
    task["verification_policy"]["method_provenance"] = method_provenance(task["validation_commands"], goal, {
        "root_guidance": {"content": (tmp_path / "AGENTS.md").read_text(), "truncated": False},
        "project_commands": {},
    })
    persist(task, context)
    first = execute(task, context, gateway, command=naive)
    second = execute(task, context, gateway, command=actual)
    assert first.ok is naive_passes and second.ok is valid
    assert first.harness_observation.data["verification_method"]["requirement_coverage"] == "unassessed"
    assert second.harness_observation.data["verification_method"]["method_relation"] == "unregistered_or_unknown"
    assert (tmp_path / "answer.py").read_text() == source
