import json
from dataclasses import replace
from pathlib import Path

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_review_agent_fallback_budget import _review_context
from tests.unit.test_review_tools import command, response, setup


def pending(kind):
    value = {"overall": {"status": "pass", "score": 1, "reason": "Checking evidence"}}
    reply = response(value)
    if kind == "continue":
        value["done"] = False
    elif kind == "truncated":
        reply = replace(reply, finish_reason="length")
    elif kind == "actions":
        value["tool_calls"] = [{"tool_name": "read_file", "args": {"path": "answer.py"}}]
    elif kind == "malformed_actions":
        value["tool_calls"] = {}
    elif kind == "native_actions":
        reply = replace(reply, raw_response={"choices": [{"message": {"tool_calls": [
            {"function": {"name": "read_file", "arguments": '{"path":"answer.py"}'}}
        ]}}]})
    elif kind == "provider_actions":
        reply = replace(reply, finish_reason="tool_calls")
    return replace(reply, content=json.dumps(value))


@pytest.mark.parametrize("kind", ["continue", "truncated", "actions", "malformed_actions",
                                  "native_actions", "provider_actions"])
def test_nonterminal_pass_cannot_complete_review_without_tools(kind):
    class Model:
        calls = 0

        def chat(self, request):
            self.calls += 1
            return pending(kind)

    client = Model()
    report = ReviewAgent(client, SchemaValidator(Path("schemas"))).evaluate(
        _review_context(deterministic_checks={"task_completion_rate": 1, "verification_pass_rate": 1}),
        "run-nonterminal")
    assert client.calls == 2
    assert report["overall"]["status"] == "partial" and report["overall"]["score"] is None
    evaluation = report["trajectory_eval"]
    assert evaluation["review_assessment"]["reason"] == "nonterminal_response"
    assert not evaluation["review_protocol_recovery"]["recovered"]
    assert len(evaluation["review_protocol_errors"]) == 2
    assert json.loads(evaluation["review_protocol_errors"][0]["response_excerpt"])["overall"]["status"] == "pass"


@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("kind", ["continue", "truncated", "malformed_actions", "native_actions", "provider_actions"])
def test_nonterminal_report_uses_existing_correction_then_preserves_real_failure(tmp_path, with_tools, kind):
    tools = setup(tmp_path) if with_tools else None

    class Model:
        calls = 0

        def chat(self, request):
            self.calls += 1
            if self.calls == 1:
                return pending(kind)
            if with_tools and self.calls == 2:
                assert request.messages[-1].role == "user"
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command("from answer import ANSWER; assert ANSWER == 42, 'actual failure'")}}]})
            if with_tools:
                assert "actual failure" in request.messages[-1].text()
            return response({"overall": {"status": "fail", "score": 0, "reason": "Independent check failed"}})

    client = Model()
    report = ReviewAgent(client, SchemaValidator(Path("schemas")), tools).evaluate(_review_context(), "run-review")
    assert client.calls == (3 if with_tools else 2)
    assert report["overall"]["status"] == "fail" and report["overall"]["score"] == 0
    assert report["trajectory_eval"]["review_assessment"] == {
        "status": "assessed", "reason": "model_judgment", "validation_scope": "response_protocol",
        "semantic_completeness": "unverified",
    }
    if tools:
        evidence = json.loads(tools.path.read_text(encoding="utf8"))
        assert len(evidence["observations"]) == 1 and not evidence["observations"][0]["ok"]
        assert (tmp_path / "answer.py").read_text() == "ANSWER = 41\n"
        assert tools.context.budget.cost_report()["tool_calls"] == 1


@pytest.mark.parametrize("done", [None, True])
def test_legacy_finality_does_not_claim_semantic_certification_or_scan_prose(done):
    class Model:
        calls = 0

        def chat(self, request):
            self.calls += 1
            value = {"overall": {"status": "partial", "reason": "I am inspecting the evidence"}}
            if done is not None:
                value["done"] = done
            return response(value)

    client = Model()
    report = ReviewAgent(client, SchemaValidator(Path("schemas"))).evaluate(_review_context(), "run-legacy")
    assert client.calls == 1
    assert report["overall"]["reason"].startswith("I am inspecting the evidence")
    assert report["trajectory_eval"]["review_assessment"]["semantic_completeness"] == "unverified"


def test_json_actions_take_priority_over_status_even_with_explicit_continuation(tmp_path):
    tools = setup(tmp_path)

    class Model:
        calls = 0

        def chat(self, request):
            self.calls += 1
            if self.calls == 1:
                reply = pending("actions")
                value = json.loads(reply.content)
                value["done"] = False
                return replace(reply, content=json.dumps(value))
            assert "ANSWER = 41" in request.messages[-1].text()
            return response({"overall": {"status": "fail", "reason": "Current artifact fails requirement"}})

    client = Model()
    report = ReviewAgent(client, tools.context.validator, tools).evaluate({}, "run-review")
    assert client.calls == 2 and report["overall"]["status"] == "fail"
    assert report["trajectory_eval"]["review_validation"]["tool_count"] == 1
