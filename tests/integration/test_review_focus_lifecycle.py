import json
from pathlib import Path

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from tests.helpers.spine import spine_response
from tests.integration.test_review_current_artifacts import Reviewer, prepare
from tests.integration.test_review_command import FakeDocPlanClient


def test_real_review_binds_current_diff_criteria_and_observations_then_accepts(tmp_path):
    run_id, run = prepare(tmp_path)
    client = Reviewer()
    assert ReviewCommand(tmp_path, run_id=run_id, model_client=client).run().status == "pass"
    payload = json.loads(client.requests[0].messages[-1].content)
    artifacts = payload["current_artifacts"]
    focus = artifacts["review_focus"]
    assert focus["changes"][0]["baseline"]["existed"] is False
    assert "+# P0 Matrix Doc Update" in focus["changes"][0]["diff"]
    assert any(c["source_kind"] == "task_contract" for c in focus["criteria"])
    raw = [json.loads(s) for s in (run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
    assert focus["task_evidence"][0]["observation_ids"] == [r["observation_id"] for r in raw]
    assert focus["semantic_coverage"] == "unassessed"
    report = json.loads((run / "eval_report.json").read_text(encoding="utf8"))
    bound = Path(report["artifact_eval"]["current_artifacts_evidence"]["evidence_ref"])
    assert json.loads(bound.read_text(encoding="utf8")) == artifacts
    assert AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run().accepted


def test_focus_reads_validated_history_before_the_recent_twelve_observation_window(tmp_path):
    InitCommand(tmp_path).run()
    run_id = PlanCommand(tmp_path, "create documentation", model_client=FakeDocPlanClient()).run().run_id
    path = "docs/p0_matrix_doc_update.md"
    class ManyObservations:
        def chat(self, request):
            return spine_response(request, narration="Create and inspect current content.", tool_calls=[
                {"tool_name": "write_file", "args": {"path": path, "content": "# Current artifact\n"}},
                *[{"tool_name": "read_file", "args": {"path": path}} for _ in range(16)],
            ])
    assert ExecuteCommand(tmp_path, run_id=run_id, model_client=ManyObservations()).run().completed == 1
    client = Reviewer()
    assert ReviewCommand(tmp_path, run_id=run_id, model_client=client).run().status == "pass"
    payload = json.loads(client.requests[0].messages[-1].content)
    assert len(payload["tool_observations"]) == 12
    assert all(r["tool_name"] != "write_file" for r in payload["tool_observations"])
    focus = payload["current_artifacts"]["review_focus"]
    change = focus["changes"][0]
    assert change["status"] == "complete" and "+# Current artifact" in change["diff"]
    run = tmp_path / ".asteria/runs" / run_id
    original = json.loads((run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()[0])
    assert change["baseline"]["observation_id"] == original["observation_id"]
    assert original["observation_id"] in focus["task_evidence"][0]["observation_ids"]
