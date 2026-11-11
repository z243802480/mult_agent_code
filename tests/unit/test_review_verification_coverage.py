from pathlib import Path

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_sparse_review_keeps_coverage_unknown_despite_complete_tasks() -> None:
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    context = {"deterministic_checks": {"task_completion_rate": 1.0}}
    report = agent._normalize({}, context, "run-coverage")

    assert report["goal_eval"] == {"requirement_coverage": None, "task_completion_rate": 1.0}
    assessed = agent._normalize({"goal_eval": {"requirement_coverage": 0.4}}, context, "run-coverage")
    assert assessed["goal_eval"]["requirement_coverage"] == 0.4


@pytest.mark.parametrize(
    ("goal_eval", "expected"),
    [
        ({"requirement_coverage": None, "task_completion_rate": 1.0}, "verification_failed"),
        ({"requirement_coverage": None, "task_completion_rate": 0.5}, "plan_gap"),
        ({"requirement_coverage": 0.4, "task_completion_rate": 1.0}, "plan_gap"),
        ({"requirement_coverage": 0.9}, "verification_failed"),
        ({}, "verification_failed"),
    ],
)
def test_coverage_reporting_preserves_failure_routing(tmp_path, goal_eval, expected) -> None:
    report = {
        "overall": {"status": "partial"},
        "goal_eval": goal_eval,
        "outcome_eval": {"verification_pass_rate": 0.5},
    }

    assert ReviewCommand(tmp_path)._failure_classification(report)["category"] == expected
