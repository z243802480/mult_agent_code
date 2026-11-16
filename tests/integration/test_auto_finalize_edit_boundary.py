import json
from pathlib import Path

import pytest

from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.jsonl_store import JsonlStore
from tests.helpers.spine import is_spine_request
from tests.integration.test_run_command import FakeExecuteClient, FakePlanClient

pytestmark = [pytest.mark.workflow, pytest.mark.spine_default]


class ScopedPlan(FakePlanClient):
    def chat(self, request):
        response = super().chat(request)
        if request.purpose == "goal_spec":
            payload = json.loads(response.content)
            payload["edit_boundary"] = {"mode": "restricted", "paths": ["complete_module.py"]}
            from dataclasses import replace
            return replace(response, content=json.dumps(payload))
        return response


class ShellSideEffect(FakeExecuteClient):
    def chat(self, request):
        response = super().chat(request)
        if is_spine_request(request):
            payload = json.loads(response.content)
            for call in payload.get("tool_calls", []):
                if call["tool_name"] == "run_command":
                    call["args"]["command"] = (
                        'python -c "from pathlib import Path; from complete_module import answer; '
                        "assert answer() == 42; Path('extra.bin').write_text('side effect')\""
                    )
            from dataclasses import replace
            return replace(response, content=json.dumps(payload))
        return response


def test_actual_successful_shell_check_outside_goal_boundary_does_not_auto_finalize(tmp_path):
    result = RunCommand(tmp_path, "Only edit complete_module.py; expose answer() returning 42.",
                        plan_model_client=ScopedPlan(), execute_model_client=ShellSideEffect(),
                        enable_research=False, permission_level="reviewed_auto").run()
    assert result.status == "completed" and result.current_phase != "ACCEPTED"
    assert (tmp_path / "extra.bin").exists()
    assert any(step.name == "accept" and step.status == "skipped" and "extra.bin" in step.summary
               for step in result.steps)
    run = tmp_path / ".asteria/runs" / result.run_id
    assert not (run / "eval_report.json").exists()  # No forced model Review in auto mode.
    report = (run / "final_report.md").read_text(encoding="utf8")
    assert "Completion: accepted" not in report
    # A later green command/contract must not silently erase the observed incident.
    store = JsonStore(SchemaValidator(Path("schemas")))
    board = store.read(run / "task_plan.json", "task_board")
    assert board["tasks"][0]["status"] == "done"
    ledger = JsonlStore(store.validator)
    evidence = ledger.read_all(run / "task_execution_evidence.jsonl", "task_execution_evidence")[-1]
    evidence["evidence_id"] += "-later-clean-round"
    evidence["contract_check"]["unscoped_changed_files"] = []
    evidence["contract_check"]["changed_files"] = ["complete_module.py"]
    ledger.append(run / "task_execution_evidence.jsonl", evidence, "task_execution_evidence")
    steps = []
    RunCommand(tmp_path, "unused")._maybe_auto_finalize(result.run_id, steps)
    assert len(steps) == 1 and steps[0].status == "skipped"
    assert "extra.bin" in steps[0].summary
    from asteria_runtime.commands.review_command import ReviewCommand
    from tests.integration.test_review_current_artifacts import Reviewer
    reviewer = Reviewer()
    ReviewCommand(tmp_path, result.run_id, model_client=reviewer).run()
    payload = json.loads(reviewer.requests[0].messages[-1].content)
    assert payload["current_artifacts"]["review_basis"]["observed_outside_current_edit_boundary"] == ["extra.bin"]


@pytest.mark.parametrize("restricted", [True, False])
def test_in_boundary_changes_and_open_goals_keep_automatic_finalization(tmp_path, restricted):
    result = RunCommand(tmp_path, "Create a module exposing answer() returning 42.",
                        plan_model_client=ScopedPlan() if restricted else FakePlanClient(),
                        execute_model_client=FakeExecuteClient() if restricted else ShellSideEffect(),
                        enable_research=False, permission_level="reviewed_auto").run()
    assert result.current_phase == "ACCEPTED"
