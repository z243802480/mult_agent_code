import json
import sys
from pathlib import Path

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_review_command import FakePlanClient, FakeExecuteClient
from tests.unit.test_review_tools import response
from tests.integration.test_review_current_artifacts import prepare, Reviewer
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.mark.parametrize("defect", [False, True])
def test_model_selects_new_check_consumes_result_and_fresh_accept_respects_verdict(tmp_path, defect):
    InitCommand(tmp_path).run()
    run_id = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient(), permission_level="auto").run().run_id
    assert ExecuteCommand(tmp_path, run_id=run_id, model_client=FakeExecuteClient()).run().completed == 1
    if defect:
        (tmp_path / "reviewed_module.py").write_text("def answer():\n    return 41\n", encoding="utf8")
    original = (tmp_path / "reviewed_module.py").read_bytes()
    run = tmp_path / ".asteria/runs" / run_id
    prefix = (run / "tool_calls.jsonl").read_bytes()
    before = json.loads((run / "cost_report.json").read_text(encoding="utf8"))

    class Model:
        requests = []

        def chat(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                payload = json.loads(request.messages[1].text())
                assert payload["review_tools"]["tools"]
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": f'"{sys.executable}" -c "from reviewed_module import answer; assert answer() == 42; print(\'independent check passed\')"'
                }}]})
            feedback = request.messages[-1].text()
            assert ("AssertionError" if defect else "independent check passed") in feedback
            return response({"overall": {"status": "fail" if defect else "pass", "score": 0 if defect else 1,
                                          "reason": "Consumed independent assertion output"}})

    client = Model()
    result = ReviewCommand(tmp_path, run_id, model_client=client).run()
    assert result.status == ("fail" if defect else "pass")
    report = json.loads((run / "eval_report.json").read_text(encoding="utf8"))
    reference = report["trajectory_eval"]["review_validation"]
    evidence = json.loads(Path(reference["evidence_ref"]).read_text(encoding="utf8"))
    assert evidence["artifact_evidence_id"] == report["artifact_eval"]["current_artifacts_evidence"]["evidence_id"]
    assert evidence["errors"] == [] and len(evidence["observations"]) == 1
    assert evidence["observations"][0]["ok"] is not defect
    calls = [json.loads(line) for line in (run / "tool_calls.jsonl").read_text(encoding="utf8").splitlines()]
    assert calls[-1]["tool_call_id"] == evidence["observations"][0]["tool_call_id"]
    assert calls[-1]["agent_id"] == "ReviewAgent"
    after = json.loads((run / "cost_report.json").read_text(encoding="utf8"))
    assert after["model_calls"] - before["model_calls"] == 2
    assert after["tool_calls"] - before["tool_calls"] == 1
    assert (run / "tool_calls.jsonl").read_bytes().startswith(prefix)
    for request in client.requests:
        assert request.metadata["review_artifacts_evidence_id"] == evidence["artifact_evidence_id"]
    assert (tmp_path / "reviewed_module.py").read_bytes() == original
    if not defect:
        assert AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run().accepted
        assert (tmp_path / "reviewed_module.py").read_bytes() == original


def test_review_recovers_durable_usage_and_checkpoints_before_spending_again(tmp_path):
    run_id, run = prepare(tmp_path)
    validator = SchemaValidator(Path("schemas"))
    store = JsonStore(validator)
    before = store.read(run / "cost_report.json", "cost_report")
    assert before["model_calls"] > 0 and before["tool_calls"] > 0
    policy = load_policy_config(tmp_path / ".asteria", validator)
    # Simulate a stale cost checkpoint after a killed process; the append-only ledgers survive.
    store.write(run / "cost_report.json", BudgetController(policy, run_id).cost_report(), "cost_report")

    class Model(Reviewer):
        def chat(self, request):
            checkpoint = store.read(run / "cost_report.json", "cost_report")
            assert checkpoint["model_calls"] == before["model_calls"] + 1
            assert checkpoint["tool_calls"] == before["tool_calls"]
            return super().chat(request)

    result = ReviewCommand(tmp_path, run_id=run_id, model_client=Model()).run()
    assert result.status == "pass"
    final = store.read(run / "cost_report.json", "cost_report")
    assert final["model_calls"] == before["model_calls"] + 1
    assert final["tool_calls"] == before["tool_calls"]
