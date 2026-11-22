"""A saved semantic verdict approves its bound input, not future edits."""

import json
import os

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_review_consumption import UnscoredReviewer
from tests.integration.test_review_current_artifacts import prepare


@pytest.mark.parametrize("change", ["artifact", "goal", "task", "guidance"])
def test_changed_review_inputs_do_not_reuse_a_saved_pass(tmp_path, change):
    run_id, run = prepare(tmp_path)
    ReviewCommand(tmp_path, run_id=run_id, model_client=UnscoredReviewer("pass")).run()
    original = (run / "eval_report.json").read_bytes()
    if change == "artifact":
        (tmp_path / "docs/p0_matrix_doc_update.md").write_text(
            "Different delivery\n", encoding="utf8"
        )
    elif change == "guidance":
        (tmp_path / "AGENTS.md").write_text("A new applicable requirement\n", encoding="utf8")
    else:
        path = run / ("goal_spec.json" if change == "goal" else "task_plan.json")
        data = json.loads(path.read_text(encoding="utf8"))
        if change == "goal":
            data["original_goal"] += " Also preserve the extra condition."
        else:
            data["tasks"][0]["acceptance"].append("An additional condition")
        path.write_text(json.dumps(data), encoding="utf8")
    result = AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run()
    assert result.accepted is False
    assert result.review_status != "pass"
    assert (run / "eval_report.json").read_bytes() == original


def test_content_unchanged_and_mtime_only_changes_keep_the_review_valid(tmp_path):
    run_id, run = prepare(tmp_path)
    ReviewCommand(tmp_path, run_id=run_id, model_client=UnscoredReviewer("pass")).run()
    path = tmp_path / "docs/p0_matrix_doc_update.md"
    os.utime(path, (1_700_000_000, 1_700_000_000))
    result = AcceptCommand(tmp_path, run_id=run_id).run()
    assert result.accepted is True
    assert result.final_report_summary["review"]["score"] is None


def test_a_change_during_the_model_call_cannot_approve_the_old_snapshot(tmp_path):
    run_id, run = prepare(tmp_path)

    class ConcurrentChange(UnscoredReviewer):
        def chat(self, request):
            (tmp_path / "docs/p0_matrix_doc_update.md").write_text(
                "Changed outside Review\n", encoding="utf8"
            )
            return super().chat(request)

    result = ReviewCommand(tmp_path, run_id=run_id, model_client=ConcurrentChange("pass")).run()
    assert result.status == "partial"


def test_promotion_invalidates_the_old_verdict_and_skip_review_cannot_waive_it(tmp_path):
    from tests.unit.test_accept_command import _workspace_ready_for_accept

    root, run, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf8")
    result = AcceptCommand(root, run_id=run.name, skip_review=True).run()
    assert result.promoted_files == ["tool.py"]
    assert result.accepted is False and result.review_status != "pass"


def test_stale_initial_review_does_not_promote_a_candidate(tmp_path):
    from tests.unit.test_accept_command import _workspace_ready_for_accept

    root, run, candidate = _workspace_ready_for_accept(tmp_path)
    (root / "tool.py").write_text("VALUE = 2\n", encoding="utf8")
    (candidate.root / "tool.py").write_text("VALUE = 3\n", encoding="utf8")
    result = AcceptCommand(root, run_id=run.name, skip_review=True).run()
    assert not result.accepted and not result.promoted_files
    assert (root / "tool.py").read_text(encoding="utf8") == "VALUE = 2\n"


def test_status_recommends_review_after_an_accepted_artifact_changes(tmp_path):
    from asteria_runtime.commands.status_command import StatusCommand

    run_id, run = prepare(tmp_path)
    ReviewCommand(tmp_path, run_id=run_id, model_client=UnscoredReviewer("pass")).run()
    assert AcceptCommand(tmp_path, run_id=run_id).run().accepted
    (tmp_path / "docs/p0_matrix_doc_update.md").write_text(
        "Changed after acceptance\n", encoding="utf8"
    )
    result = StatusCommand(tmp_path).run()
    context = result.current_context
    assert context["recommended_next_command"] == "review"
    assert result.to_dict()["workflow_state"] == "ready_for_review"
