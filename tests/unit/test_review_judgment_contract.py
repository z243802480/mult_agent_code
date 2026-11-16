import json
from pathlib import Path

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.mark.parametrize("legacy", [False, True])
def test_model_judgment_and_persisted_runtime_report_have_distinct_contracts(legacy):
    validator = SchemaValidator(Path("schemas"))
    persisted = json.loads(json.dumps(validator.schema("eval_report")))
    reply = {"overall": {"status": "fail", "score": 0.2, "reason": "Second original condition is unmet"}}
    if legacy:
        reply.update({"goal_eval": {"requirement_coverage": 0.5},
                      "artifact_eval": {"evidence": ["answer.py:2"]}})

    class Model:
        def chat(self, request):
            exposed = json.loads(request.messages[0].text().split("Review judgment JSON schema:\n", 1)[1])
            assert exposed["required"] == ["overall"]
            validator._validate_node(exposed, reply, "$")
            return ChatResponse(content=json.dumps(reply), finish_reason="stop", usage=TokenUsage(1, 1, 2),
                                model_provider="fake", model_name="judgment", raw_response={})

    agent = ReviewAgent(Model(), validator)
    report = agent.evaluate({"deterministic_checks": {"task_completion_rate": 1, "verification_pass_rate": 0.75},
                             "cost_report": {"model_calls": 3, "tool_calls": 4, "status": "within_budget"}}, "run-judgment")
    assert report["overall"]["status"] == "fail"  # Green process cannot overwrite a semantic failure.
    assert report["goal_eval"]["task_completion_rate"] == 1
    assert report["goal_eval"]["requirement_coverage"] == (0.5 if legacy else None)
    assert report["cost_eval"]["model_calls"] == 3
    assert report["outcome_eval"]["verification_pass_rate"] == 0.75
    validator.validate("eval_report", report)
    assert validator.schema("eval_report") == persisted
    assert len(persisted["required"]) == 8


def test_judgment_description_still_requires_a_verdict_and_is_not_a_new_gate():
    agent = ReviewAgent(None, SchemaValidator(Path("schemas")))
    schema = agent._model_response_schema()
    assert not agent._has_judgment({})
    assert agent._has_judgment({"overall": {"status": "partial"}})
    assert schema["properties"]["overall"] == agent.validator.schema("eval_report")["properties"]["overall"]
