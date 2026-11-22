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


@pytest.mark.parametrize("status", ["pass", "partial", "fail"])
@pytest.mark.parametrize("invalid", [
    pytest.param(99, id="percent-scale"), pytest.param(-0.1, id="negative"),
    pytest.param(1.01, id="above-one"), pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"), pytest.param(float("-inf"), id="negative-infinity"),
    pytest.param(True, id="bool-true"), pytest.param(False, id="bool-false"),
    pytest.param("not-a-score", id="text"), pytest.param({}, id="object"),
    pytest.param([], id="array"), pytest.param(10**400, id="overflow-integer"),
])
def test_invalid_model_score_is_unassessed_without_replacing_the_judgment(status, invalid):
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    original = {"status": status, "score": invalid, "reason": "Artifact judgment remains independent"}
    report = agent._normalize({"overall": original}, {
        "deterministic_checks": {"task_completion_rate": 1, "verification_pass_rate": 1},
    }, "run-score")
    assert report["overall"]["score"] is None
    assert report["overall"]["score_source"] == "unassessed"
    assert report["overall"]["status"] == status
    assert original["reason"] in report["overall"]["reason"]
    assert "unassessed" in report["overall"]["reason"]
    assert original["score"] is invalid
    agent.validator.validate("eval_report", report)


@pytest.mark.parametrize("score,expected", [(0, 0.0), (1, 1.0), (0.99, 0.99), ("0.99", 0.99), ("1", 1.0), ("0", 0.0)])
def test_valid_scores_and_legacy_numeric_strings_keep_their_scale(score, expected):
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    result = agent._normalize({"overall": {"status": "pass", "score": score, "reason": "supported"}}, {}, "run-score")
    assert result["overall"]["score"] == expected
    assert result["overall"]["score_source"] == "model_assessment"


def test_old_persisted_out_of_range_reports_remain_readable_without_rewriting(tmp_path):
    from asteria_runtime.storage.json_store import JsonStore
    validator = SchemaValidator(Path("schemas"))
    report = ReviewAgent(None, validator)._normalize({"overall": {"status": "pass", "score": 0.99}}, {}, "run-old")
    report["overall"]["score"] = 99
    store = JsonStore(validator)
    path = tmp_path / "eval_report.json"
    store.write(path, report, "eval_report")
    before = path.read_bytes()
    assert store.read(path, "eval_report")["overall"]["score"] == 99
    assert path.read_bytes() == before
