import json
from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.core.verification_guidance import ARTIFACT_VERIFICATION_GUIDANCE
from tests.integration.test_review_current_artifacts import Reviewer, prepare
from tests.integration.test_verification_boundary_feedback import SideEffects, scoped


def test_review_binds_real_limits_without_rewriting_model_proposals_or_legacy_profiles(tmp_path):
    run_id, run = prepare(tmp_path)
    goal_path = run / "goal_spec.json"
    goal = json.loads(goal_path.read_text(encoding="utf8"))
    goal["budget"] = {"max_model_calls": 1, "max_iterations": 1}
    goal_path.write_text(json.dumps(goal), encoding="utf8")
    before = goal_path.read_bytes()
    profiles = (run / "runtime_profiles.jsonl").read_bytes()
    reviewer = Reviewer()
    assert ReviewCommand(tmp_path, run_id=run_id, model_client=reviewer).run().status == "pass"
    request = reviewer.requests[0]
    payload = json.loads(request.messages[-1].content)
    facts = payload["current_artifacts"]["review_basis"]["runtime_budget"]
    assert facts["configured_limits"]["max_model_calls_per_goal"] > 1
    assert facts["pressure"]["status"] == "within_budget"
    assert facts["temporal_scope"] == "current_review_start"
    assert facts["recorded_outer_iterations"] is None  # Direct Execute: no fabricated outer cycle count.
    assert "historical" in facts["interpretation"]
    report = json.loads((run / "eval_report.json").read_text(encoding="utf8"))
    bound = json.loads(Path(report["artifact_eval"]["current_artifacts_evidence"]["evidence_ref"]).read_text(encoding="utf8"))
    assert bound["review_basis"]["runtime_budget"] == facts
    assert goal_path.read_bytes() == before and (run / "runtime_profiles.jsonl").read_bytes() == profiles


def test_actual_doer_receives_shared_verification_coverage_and_budget_facts(tmp_path):
    run_id, run, _ = scoped(tmp_path)
    doer = SideEffects(False)
    assert ExecuteCommand(tmp_path, run_id=run_id, model_client=doer).run().completed == 1
    seed = json.loads(doer.requests[0].messages[1].content)
    assert ARTIFACT_VERIFICATION_GUIDANCE in doer.requests[0].messages[0].content
    recorded = json.loads((run / "runtime_profiles.jsonl").read_text(encoding="utf8"))
    assert seed["runtime_budget"]["configured_limits"]["max_model_calls_per_goal"] == recorded["budget"]["max_model_calls"]
    assert seed["runtime_budget"]["scope"] == "shared_goal"
