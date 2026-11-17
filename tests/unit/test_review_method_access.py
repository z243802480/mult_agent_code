from dataclasses import replace
import hashlib
import json

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.core.review_evidence import ReviewEvidence
from asteria_runtime.core.review_tools import REVIEW_TURN_CONTRACT
from asteria_runtime.models.base import ChatMessage, ChatRequest
from tests.unit.test_review_tools import setup, invoke, response, command


def bind_method(tools, cmd):
    observed = {"run_id": tools.context.run_id, "task_id": "task-original", "tool_call_id": "call-original",
                "observation_id": "obs-original", "tool_name": "run_tests", "ok": True,
                "observation": {"data": {"requested_command": cmd, "returncode": 0, "stdout": "original observation"}}}
    call = {"run_id": tools.context.run_id, "task_id": "task-original", "tool_call_id": "call-original",
            "tool_name": "run_tests", "agent_id": "CoderAgent"}
    board = {"tasks": [{"task_id": "task-original", "validation_commands": [cmd]}]}
    tools.evidence = ReviewEvidence(tools.context, tools.artifacts["evidence_id"], tools.task["task_id"],
                                   {"goal_spec": {"original_goal": "ANSWER must equal 42; equivalent expressions are valid"}},
                                   [observed], [call], board)
    return tools.evidence.input_view()


def test_long_exact_method_pages_and_original_observation_are_directly_addressable(tmp_path):
    tools = setup(tmp_path)
    cmd = "original command\n" + "quoted 'line' \\\n" * 700
    view = bind_method(tools, cmd)
    entry = view["review_evidence"]["verification_methods"]["current"][0]
    chunks, offset = [], 0
    while offset is not None:
        reply = invoke(tools, "inspect_evidence", {"evidence_ref": entry["method_ref"], "offset": offset})[0]
        header, content = reply.payload.split("\n", 1)
        chunks.append(content)
        offset = json.loads(header)["next_offset"]
    method = json.loads("".join(chunks))
    assert method["command"] == cmd and len(cmd) > 4000
    assert method["command_sha256"] == hashlib.sha256(cmd.encode()).hexdigest()
    assert method["requirement_coverage"] == "unassessed"
    assert method["observations"][0]["selection_origin"] == "not_recorded"
    chunks, offset = [], 0
    while offset is not None:
        original = invoke(tools, "inspect_evidence", {"evidence_ref": entry["observation_ref"], "offset": offset})[0]
        header, content = original.payload.split("\n", 1)
        chunks.append(content)
        offset = json.loads(header)["next_offset"]
    assert json.loads("".join(chunks))["observation"]["data"]["stdout"] == "original observation"
    assert not tools.finish("completed")["copy_created"]


@pytest.mark.parametrize("expression,valid", [("42", True), ("6 * 7", True), ("41", False)])
def test_selected_method_reaches_model_and_independent_result_overrides_historical_green(tmp_path, expression, valid):
    tools = setup(tmp_path, content=f"ANSWER = {expression}\n")
    cmd = command("from answer import ANSWER; assert ANSWER == 42, 'actual mismatch'; print('actual value checked')")
    view = bind_method(tools, cmd)
    evidence = tools.evidence
    # Keep this constructed immutable snapshot; production bind_evidence is separately covered.
    tools.bind_evidence = lambda context: view

    class Model:
        turn = 0

        def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                current = json.loads(request.messages[1].text())["review_evidence"]["verification_methods"]["current"]
                assert len(current) == 1
                return response({"tool_calls": [{"tool_name": "inspect_evidence", "args": {"evidence_ref": current[0]["method_ref"]}}]})
            if self.turn == 2:
                section = json.loads(evidence.sections[view["review_evidence"]["verification_methods"]["current"][0]["method_ref"]]["content"])
                assert json.dumps(section, ensure_ascii=False, separators=(",", ":"), sort_keys=True) in request.messages[-1].text()
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {"command": section["command"]}}]})
            assert ("exited 0" if valid else "actual mismatch") in request.messages[-1].text()
            return response({"overall": {"status": "pass" if valid else "fail", "reason": "Actual value checked"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == ("pass" if valid else "fail")
    record = json.loads(tools.path.read_text(encoding="utf8"))
    assert len(record["model_requests"]) == 3
    first, second, third = record["model_requests"]
    assert first["observations"] == []
    assert len(second["observations"]) == 1 and second["observations"][0]["payload_included"]
    assert "/method/" in second["observations"][0]["evidence_ref"]
    assert third["observations"][-1]["tool_name"] == "run_tests" and third["observations"][-1]["payload_included"]
    assert all(x["status"] == "returned" and x["scope"] == "request_assembly_only" for x in record["model_requests"])
    tools.context.validator.validate("review_validation", {k: v for k, v in record.items() if k != "model_requests"})
    assert (tmp_path / "answer.py").read_text() == f"ANSWER = {expression}\n"


def test_requests_distinguish_payload_compaction_absence_failure_and_unforwarded_read(tmp_path):
    tools = setup(tmp_path)
    view = bind_method(tools, command("print('original command')"))
    ref = view["review_evidence"]["verification_methods"]["current"][0]["method_ref"]

    class Client:
        fail = False

        def chat(self, request):
            if self.fail:
                raise RuntimeError("provider unavailable")
            return response({})

    client = Client()
    bounded = tools.bounded_client(client)
    request = ChatRequest(purpose="run_review", model_tier="strong", messages=[ChatMessage("user", "initial")])
    bounded.chat(request)
    observed = invoke(tools, "inspect_evidence", {"evidence_ref": ref})[0]
    assert len(tools.model_requests) == 1 and not tools.model_requests[0]["observations"]
    def feedback(payloads):
        return replace(request, messages=[ChatMessage("user", _observation_feedback(
            [observed], "json", include_payloads=payloads, json_turn_contract=REVIEW_TURN_CONTRACT))])
    bounded.chat(feedback(True))
    bounded.chat(feedback(False))
    bounded.chat(request)
    client.fail = True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        bounded.chat(feedback(True))
    stored = tools.finish("completed")["model_requests"]
    assert stored[1]["observations"][0]["payload_included"]
    assert not stored[2]["observations"][0]["payload_included"]
    assert stored[3]["observations"] == []
    assert stored[4]["status"] == "failed" and stored[4]["observations"][0]["payload_included"]
    assert stored[1]["messages_sha256"] != stored[2]["messages_sha256"]


def test_method_caps_and_ambiguous_or_foreign_observations_do_not_create_bindings(tmp_path, monkeypatch):
    import asteria_runtime.core.review_evidence as module
    tools = setup(tmp_path)
    bind_method(tools, "method")
    origin = tools.evidence.origins["records"][0]
    row = json.loads(tools.evidence.sections[origin["evidence_ref"]]["content"])
    board = {"tasks": [{"task_id": "task-original", "validation_commands": ["method"]}]}
    for observations in [[row, row], [{**row, "run_id": "foreign"}]]:
        evidence = ReviewEvidence(tools.context, "snapshot-test", tools.task["task_id"], {}, observations, [], board)
        assert evidence.input_view()["review_evidence"]["verification_methods"]["method_count"] == 0
    monkeypatch.setattr(module, "MAX_SECTION_CHARS", 30)
    view = bind_method(tools, "long command" * 100)
    ref = view["review_evidence"]["verification_methods"]["current"][0]["method_ref"]
    assert tools.evidence.sections[ref]["truncated"]
    assert sum(s["stored_characters"] for s in tools.evidence.sections.values()) <= module.MAX_SNAPSHOT_CHARS
    assert not invoke(tools, "inspect_evidence", {"evidence_ref": "other-run/method/" + "0" * 64})[0].ok
    tools.finish("completed")
