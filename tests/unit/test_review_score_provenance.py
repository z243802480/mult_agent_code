"""Executed checks and a reviewer's judgment are different measurements."""
from pathlib import Path

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.mark.parametrize("status", ["pass", "partial", "fail"])
@pytest.mark.parametrize("command_rate", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("model_score", ["absent", None, 0.2])
def test_command_rate_never_fills_model_score_or_requirement_coverage(status, command_rate, model_score):
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    judgment = {"status": status, "reason": "A condition has only behavioral evidence"}
    if model_score != "absent":
        judgment["score"] = model_score
    report = agent._normalize({"overall": judgment}, {
        "deterministic_checks": {"task_completion_rate": 1, "verification_pass_rate": command_rate},
        "correctness_signal": {"status": "pass", "score": command_rate, "reason": "Command outcomes"},
    }, "run-source")
    expected = 0.2 if model_score == 0.2 else None
    assert report["overall"]["status"] == status
    assert report["overall"]["score"] == expected
    assert report["overall"]["score_source"] == ("model_assessment" if expected is not None else "unassessed")
    assert judgment["reason"] in report["overall"]["reason"]
    assert report["outcome_eval"]["verification_pass_rate"] == command_rate
    assert report["goal_eval"]["requirement_coverage"] is None
    assert report["goal_eval"]["requirement_coverage_runtime_verified"] is False
    agent.validator.validate("eval_report", report)


def test_green_execution_without_judgment_or_numeric_coverage_remains_unassessed():
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    report = agent._normalize({}, {
        "deterministic_checks": {"task_completion_rate": 1, "verification_pass_rate": 1},
        "correctness_signal": {"status": "pass", "score": 1},
    }, "run-no-judgment")
    assert report["overall"]["status"] == "partial"
    assert report["overall"]["score"] is None
    assert report["overall"]["score_source"] == "unassessed"
