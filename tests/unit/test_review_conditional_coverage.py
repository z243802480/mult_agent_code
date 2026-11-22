"""Controls for the evaluation oracle and existing Review revision semantics."""
import runpy
import sys
from types import ModuleType
from pathlib import Path
import unittest

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from test_review_tools import setup, response, command

FIXTURE = runpy.run_path(str(Path(__file__).resolve().parents[2] / "benchmarks/review_cases/conditional_aggregation.py"))


@pytest.mark.parametrize("variant", ["good", "alternative", "bad-disabled", "bad-region"])
def test_behavior_oracle_accepts_equivalence_and_distinguishes_conditional_defects(variant):
    namespace = {}
    exec(FIXTURE["VARIANTS"][variant], namespace)
    result = FIXTURE["verify"](namespace["aggregate"])
    failures = {row["id"] for row in result["checks"] if not row["ok"]}
    expected = {"bad-disabled": {"disabled-missing-payload", "disabled-invalid-region", "disabled-payload-not-accessed"},
                "bad-region": {"unselected-invalid-quantity", "unselected-missing-payload", "unselected-payload-not-accessed"}}
    assert result["count"] == 22
    assert failures == expected.get(variant, set())
    assert result["ok"] is (variant in {"good", "alternative"})


@pytest.mark.parametrize("variant", list(FIXTURE["VARIANTS"]))
def test_shallow_project_checks_alone_do_not_distinguish_these_defects(monkeypatch, variant):
    module = ModuleType("aggregate")
    exec(FIXTURE["VARIANTS"][variant], module.__dict__)
    monkeypatch.setitem(sys.modules, "aggregate", module)
    checks = {}
    exec(FIXTURE["PROJECT_CHECKS"], checks)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(checks["AggregateTests"])
    result = unittest.TestResult()
    suite.run(result)
    assert result.testsRun == 2 and result.wasSuccessful()


@pytest.mark.parametrize("correct", [True, False])
def test_revised_check_and_its_actual_observations_remain_available_to_review_judgment(tmp_path, correct):
    tools = setup(tmp_path)

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            if self.count == 1:
                code = "from answer import ANSWER; assert ANSWER == 42, 'wrong method assumption'"
            elif self.count == 2:
                assert "wrong method assumption" in request.messages[-1].text()
                code = "from answer import ANSWER; assert ANSWER == " + ("41" if correct else "43")
            else:
                feedback = request.messages[-1].text()
                assert ("exited 0" in feedback) is correct
                return response({"overall": {"status": "pass" if correct else "fail", "score": int(correct),
                                             "reason": "Judgment follows the corrected behavioral check."}})
            return response({"tool_calls": [{"tool_name": "run_tests", "args": {"command": command(code)}}]})

    model = Model()
    report = ReviewAgent(model, tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == ("pass" if correct else "fail")
    assert report["trajectory_eval"]["review_validation"]["errors"] == []
    assert report["trajectory_eval"]["review_validation"]["command_check_count"] == 2
    assert (tmp_path / "answer.py").read_text() == "ANSWER = 41\n"
