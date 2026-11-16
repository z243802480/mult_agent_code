import json
from pathlib import Path

from asteria_runtime.commands import review_command as module
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_review_command import FakeDocPlanClient, FakeDocReadbackExecuteClient


class Reviewer:
    def __init__(self, status="pass", fail=False):
        self.status, self.fail = status, fail
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("synthetic unavailable reviewer")
        return ChatResponse(content=json.dumps({"overall": {
            "status": self.status, "score": 0.9, "reason": "Current artifact assessed against its requirements",
        }}), finish_reason="stop", usage=TokenUsage(1, 1, 2),
            model_provider="fake", model_name="review-evidence-fixture", raw_response={})


def prepare(root):
    InitCommand(root).run()
    plan = PlanCommand(root, "create a documentation artifact", model_client=FakeDocPlanClient()).run()
    assert ExecuteCommand(root, run_id=plan.run_id, model_client=FakeDocReadbackExecuteClient()).run().completed == 1
    return plan.run_id, root / ".asteria/runs" / plan.run_id


def test_default_review_reaches_model_with_current_content_despite_green_historical_readback(tmp_path, monkeypatch):
    run_id, run = prepare(tmp_path)
    path = tmp_path / "docs/p0_matrix_doc_update.md"
    path.write_text("Current artifact has a known defect.\n", encoding="utf8")
    client = Reviewer("fail")
    monkeypatch.setattr(module, "create_model_client", lambda *args: client)
    result = ReviewCommand(tmp_path, run_id=run_id).run()
    assert result.status == "fail" and len(client.requests) == 1
    payload = json.loads(client.requests[0].messages[-1].content)
    assert payload["deterministic_checks"]["task_completion_rate"] == 1
    assert payload["current_artifacts"]["files"][0]["content"].splitlines() == path.read_text(encoding="utf8").splitlines()
    store = JsonStore(SchemaValidator(Path("schemas")))
    report = store.read(run / "eval_report.json", "eval_report")
    evidence = report["artifact_eval"]["current_artifacts_evidence"]
    assert client.requests[0].metadata["review_artifacts_evidence_id"] == evidence["evidence_id"]
    assert client.requests[0].metadata["review_artifacts_evidence_ref"] == evidence["evidence_ref"]
    assert store.read(Path(evidence["evidence_ref"]), "review_artifacts") == payload["current_artifacts"]
    assert report["trajectory_eval"]["review_tier"]["accepted_without_model"] is False
    assert path.read_text(encoding="utf8") == "Current artifact has a known defect.\n"


def test_unavailable_reviewer_does_not_approve_completed_run(tmp_path):
    run_id, run = prepare(tmp_path)
    result = ReviewCommand(tmp_path, run_id=run_id, model_client=Reviewer(fail=True)).run()
    report = json.loads((run / "eval_report.json").read_text(encoding="utf8"))
    assert result.status == "partial" and result.score is None
    assert report["outcome_eval"]["verification_pass_rate"] == 1
    assert report["goal_eval"]["requirement_coverage"] is None
    assert report["trajectory_eval"]["review_assessment"]["status"] == "unavailable"


def test_model_pass_cannot_hide_missing_current_artifact(tmp_path):
    run_id, run = prepare(tmp_path)
    store = JsonStore(SchemaValidator(Path("schemas")))
    board = store.read(run / "task_plan.json", "task_board")
    board["tasks"][0]["expected_artifacts"].append("missing-output")
    store.write(run / "task_plan.json", board, "task_board")
    result = ReviewCommand(tmp_path, run_id=run_id, model_client=Reviewer()).run()
    report = store.read(run / "eval_report.json", "eval_report")
    assert result.status == "partial" and result.score is None
    assert report["trajectory_eval"]["model_overall_before_evidence_check"]["status"] == "pass"
    assert report["artifact_eval"]["current_artifacts_evidence"]["complete"] is False


def test_client_initialization_failure_is_unavailable_without_fabricated_model_attempt(tmp_path, monkeypatch):
    run_id, run = prepare(tmp_path)
    before = json.loads((run / "cost_report.json").read_text(encoding="utf8"))
    def unavailable(*args):
        raise RuntimeError("synthetic client configuration failure")
    monkeypatch.setattr(module, "create_model_client", unavailable)
    result = ReviewCommand(tmp_path, run_id=run_id).run()
    report = json.loads((run / "eval_report.json").read_text(encoding="utf8"))
    after = json.loads((run / "cost_report.json").read_text(encoding="utf8"))
    assert result.status == "partial" and result.score is None
    assert after["model_calls"] == before["model_calls"]
    assert report["trajectory_eval"]["review_model_initialization_error"] == {"error_type": "RuntimeError"}
