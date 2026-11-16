import json
from pathlib import Path

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_review_current_artifacts import Reviewer, prepare


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
