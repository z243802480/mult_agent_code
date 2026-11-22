from copy import deepcopy
from pathlib import Path

import pytest

from asteria_runtime.core.review_summary import summarize_review
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.mark.parametrize(
    "invalid", [None, 99, -0.1, float("nan"), float("inf"), True, "0.9", 10**400]
)
def test_legacy_or_unknown_quantities_do_not_turn_into_coverage(invalid):
    report = {
        "run_id": "run-view",
        "overall": {"status": "pass", "score": invalid, "reason": "Original reason"},
        "goal_eval": {
            "requirement_coverage": invalid,
            "requirement_coverage_runtime_verified": False,
        },
        "outcome_eval": {"verification_pass_rate": 1},
    }
    original = deepcopy(report)
    view = summarize_review(report)
    assert view["status"] == "pass" and view["reason"] == "Original reason"
    assert view["score"] is None and view["requirement_coverage"] is None
    assert view["verification_pass_rate"] == 1
    assert view["requirement_coverage_runtime_verified"] is False
    assert report == original  # NaN identity preserved; nothing is normalized back into the report.
    validator = SchemaValidator(Path("schemas"))
    validator.validate(
        "final_report_summary",
        {
            "schema_version": "0.1.0",
            "run_id": "run-view",
            "status": "completed",
            "review_status": "pass",
            "review": view,
            "final_report_path": "final_report.md",
            "workflow_state": "accepted",
            "current_blocker": None,
            "recommended_next_command": None,
            "model_selection": {},
            "blockers": [],
            "next_actions": [],
            "updated_at": "2026-11-22T00:00:00Z",
        },
    )


def test_model_coverage_is_labelled_and_never_independently_certified_by_projection():
    view = summarize_review(
        {
            "overall": {"status": "partial", "score": 0.8},
            "goal_eval": {
                "requirement_coverage": 0.5,
                "requirement_coverage_source": "model_assessment",
            },
            "outcome_eval": {"verification_pass_rate": 1},
        }
    )
    assert view["requirement_coverage"] == 0.5
    assert view["requirement_coverage_source"] == "model_assessment"
    assert view["requirement_coverage_runtime_verified"] is False
    assert view["status"] == "partial"
