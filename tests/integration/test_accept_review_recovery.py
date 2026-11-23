"""Accept routes missing/expired approval to Review without weakening the guard."""

import json

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_review_consumption import UnscoredReviewer
from tests.integration.test_review_current_artifacts import prepare


@pytest.mark.parametrize("case", ["missing", "unbound", "changed", "unavailable"])
def test_accept_reports_review_recovery_for_unusable_approval(tmp_path, case):
    run_id, run = prepare(tmp_path)
    ReviewCommand(tmp_path, run_id=run_id, model_client=UnscoredReviewer("pass")).run()
    path = run / "eval_report.json"
    if case == "missing":
        path.unlink()
    elif case == "changed":
        (tmp_path / "docs/p0_matrix_doc_update.md").write_text(
            "Changed artifact\n", encoding="utf8"
        )
    else:
        report = json.loads(path.read_text(encoding="utf8"))
        if case == "unbound":
            report["artifact_eval"].pop("review_binding")
        else:
            report["artifact_eval"]["review_binding"] = {}
        path.write_text(json.dumps(report), encoding="utf8")
    before = path.read_bytes() if path.exists() else None
    result = AcceptCommand(tmp_path, run_id=run_id, skip_review=True, promote_all=False).run()
    assert not result.accepted and result.review_status == "unknown"
    assert result.recommended_next_command == "review"
    assert any("asteria review" in x for x in result.next_actions)
    assert all("asteria debug" not in x for x in result.next_actions)
    assert result.final_report_summary["recommended_next_command"] == "review"
    assert (path.read_bytes() if path.exists() else None) == before
