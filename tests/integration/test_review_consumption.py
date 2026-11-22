"""Review judgments survive delivery; execution success never fills unknown coverage."""

import json

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from tests.integration.test_review_current_artifacts import prepare


class UnscoredReviewer:
    def __init__(self, status):
        self.status = status

    def chat(self, request):
        return ChatResponse(
            content=json.dumps(
                {
                    "overall": {
                        "status": self.status,
                        "reason": "Only the recorded behaviors were checked",
                    }
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="consumption-control",
            raw_response={},
        )


@pytest.mark.parametrize("status", ["pass", "partial", "fail"])
def test_unscored_judgment_reaches_cli_report_and_accept_without_changing_verdict(tmp_path, status):
    run_id, run = prepare(tmp_path)
    review = ReviewCommand(tmp_path, run_id=run_id, model_client=UnscoredReviewer(status)).run()
    original = (run / "eval_report.json").read_bytes()
    payload = review.to_dict()["review"]
    assert payload["status"] == status and payload["score"] is None
    assert payload["score_source"] == "unassessed"
    assert payload["requirement_coverage"] is None
    assert payload["verification_pass_rate"] == 1
    assert "Only the recorded behaviors were checked" in review.to_text()
    assert "Requirement coverage: unassessed" in review.to_text()
    assert "Score: unassessed" in review.to_text()
    # skip_review prevents another reviewer call in the negative controls; it cannot waive pass.
    accept = AcceptCommand(tmp_path, run_id=run_id, skip_review=status != "pass").run()
    assert accept.accepted is (status == "pass")
    assert accept.review_status == status
    summary = json.loads((run / "final_report_summary.json").read_text(encoding="utf8"))
    assert summary["review"] == payload
    assert "Only the recorded behaviors were checked" in accept.final_report_path.read_text(
        encoding="utf8"
    )
    assert "Requirement coverage: unassessed" in accept.final_report_path.read_text(encoding="utf8")
    assert (run / "eval_report.json").read_bytes() == original
