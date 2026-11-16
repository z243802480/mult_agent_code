from dataclasses import replace
import hashlib
import json

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.core.review_evidence import verification_origins
from asteria_runtime.core.agent_harness import _model_facing_payload
from test_review_tools import setup, invoke, response, command


def snapshot(tools, content=None):
    view = tools.bind_evidence(content or {"trajectory": {"events": ["unique-original" * 2000]},
                                          "current_artifacts": {"current": "kept"}})
    return tools.evidence, view


def test_paged_history_preserves_content_and_source_hash_without_copy(tmp_path):
    tools = setup(tmp_path)
    evidence, view = snapshot(tools)
    ref = view["trajectory"]["events"]["deferred_evidence_ref"]
    assert view["current_artifacts"] == {"current": "kept"}
    original = evidence.sections[ref]["content"]
    chunks, offset = [], 0
    while offset is not None:
        result = invoke(tools, "inspect_evidence", {"evidence_ref": ref, "offset": offset})[0]
        assert result.ok
        payload = result.payload
        assert "source_snapshot_id" in payload
        data = json.loads(payload.split("\n", 1)[0])
        chunks.append(payload.split("\n", 1)[1])
        offset = data["next_offset"]
    assert "".join(chunks) == original
    assert hashlib.sha256(original.encode()).hexdigest() == evidence.sections[ref]["content_sha256"]
    stored = json.loads(evidence.path.read_text())
    tools.context.validator.validate("review_evidence", stored)
    assert not tools.finish("completed")["copy_created"]


@pytest.mark.parametrize("reference", [".env", "../tool_observations.jsonl", "foreign/observations", "secrets/token"])
def test_lookup_rejects_paths_and_foreign_references(tmp_path, reference):
    tools = setup(tmp_path)
    snapshot(tools)
    assert not invoke(tools, "inspect_evidence", {"evidence_ref": reference})[0].ok
    assert not tools.finish("completed")["copy_created"]


def test_scoped_owner_and_paging_bounds(tmp_path):
    tools = setup(tmp_path)
    evidence, _ = snapshot(tools)
    ref = next(iter(evidence.sections))
    owner = replace(tools.context, task_id=tools.task["task_id"])
    for ctx in [replace(owner, task_id="other"), replace(owner, run_id="other"),
                replace(owner, run_dir_override=tmp_path / "other")]:
        with pytest.raises(PermissionError):
            evidence.run(ctx, ref)
    for args in [{"offset": -1}, {"offset": True}, {"limit": 4001}, {"limit": False}]:
        with pytest.raises(ValueError):
            evidence.run(owner, ref, **args)
    assert evidence.run(owner, ref, offset=999999).data["next_offset"] is None
    tools.finish("completed")


def test_small_history_is_on_demand_and_no_tools_retains_original_context(tmp_path):
    tools = setup(tmp_path)
    source = {"trajectory": {"events": ["small"]}}
    view = tools.bind_evidence(source)
    ref = view["trajectory"]["events"]["deferred_evidence_ref"]
    assert json.loads(tools.evidence.sections[ref]["content"]) == ["small"]
    assert source == {"trajectory": {"events": ["small"]}}
    tools.allowed.clear()
    assert tools.bind_evidence(source) is source
    tools.finish("completed")


def test_recorded_executor_is_not_method_designer_or_requirement_coverage():
    observation = {"run_id": "r", "task_id": "t", "tool_name": "run_tests", "tool_call_id": "c",
                   "observation_id": "o", "ok": True, "observation": {"data": {"requested_command": "test", "returncode": 0}}}
    call = {"run_id": "r", "task_id": "t", "tool_call_id": "c", "tool_name": "run_tests", "agent_id": "CoderAgent"}
    board = {"tasks": [{"task_id": "t", "validation_commands": ["test"]}]}
    facts = verification_origins("r", board, [observation, {**observation, "run_id": "foreign"}], [call])
    assert facts["record_count"] == 1
    row = facts["records"][0]
    assert row["recorded_executor"] == "CoderAgent" and row["selection_origin"] == "not_recorded"
    assert row["method_relation"] == "current_declared_task_method"
    assert row["requirement_coverage"] == "unassessed"
    assert verification_origins("r", board, [observation], [call, call])["records"][0]["recorded_executor"] == "unknown"
    assert verification_origins("r", board, [observation], [{**call, "task_id": "other"}])["records"][0]["recorded_executor"] == "unknown"


def test_model_reads_history_then_executes_independent_check_and_coverage_stays_labeled(tmp_path):
    tools = setup(tmp_path)

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            if self.count == 1:
                view = json.loads(request.messages[1].text())
                ref = view["trajectory"]["events"]["deferred_evidence_ref"]
                return response({"tool_calls": [{"tool_name": "inspect_evidence", "args": {"evidence_ref": ref}}]})
            if self.count == 2:
                assert "unique-original" in request.messages[-1].text()
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command("from answer import ANSWER; assert ANSWER == 42, 'fresh failure'")}}]})
            assert "fresh failure" in request.messages[-1].text()
            return response({"goal_eval": {"requirement_coverage": 0.8, "requirement_coverage_runtime_verified": True},
                             "overall": {"status": "fail", "score": 0, "reason": "Fresh assertion failed"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate(
        {"trajectory": {"events": ["unique-original" * 2000]},
         "deterministic_checks": {"task_completion_rate": 1, "verification_pass_rate": 0.75}}, "run-review")
    assert report["overall"]["status"] == "fail"
    assert report["goal_eval"]["requirement_coverage"] == 0.8
    assert report["goal_eval"]["requirement_coverage_source"] == "model_assessment"
    assert report["goal_eval"]["requirement_coverage_runtime_verified"] is False
    assert report["goal_eval"]["task_completion_rate"] == 1
    assert report["outcome_eval"]["verification_pass_rate"] == 0.75
    assert report["trajectory_eval"]["review_validation"]["evidence_read_count"] == 1
    assert report["trajectory_eval"]["review_validation"]["command_check_count"] == 1
    assert (tmp_path / "answer.py").read_text() == "ANSWER = 41\n"


def test_history_cap_is_explicit(monkeypatch, tmp_path):
    import asteria_runtime.core.review_evidence as module
    monkeypatch.setattr(module, "MAX_SNAPSHOT_CHARS", 30)
    tools = setup(tmp_path)
    evidence, view = snapshot(tools)
    section = evidence.sections[view["trajectory"]["events"]["deferred_evidence_ref"]]
    assert section["truncated"] and section["stored_characters"] == 30
    assert section["characters"] > 30
    tools.finish("completed")


def test_payload_preserves_page_as_text():
    content = '"\\n' * 1000
    payload = _model_facing_payload("inspect_evidence", {"content": content, "next_offset": 3000})
    assert payload.split("\n", 1)[1] == content


def test_process_judgments_are_not_prefilled_but_scope_current_facts_and_evidence_survive(tmp_path):
    tools = setup(tmp_path)
    original_scope = {"task_id": "t", "read_scope": ["answer.py"], "write_scope": [], "allowed_tools": ["read_file"]}
    for judgment in ["INHERITED_PASS", "INHERITED_FAIL"]:
        source = {"goal_spec": {"original_goal": "ANSWER must equal 42; equivalent expressions are valid",
                                "normalized_goal": judgment, "edit_boundary": {"mode": "restricted", "paths": ["answer.py"]}},
                  "task_plan": {"tasks": [{**original_scope, "status": "done", "acceptance": [judgment]},
                                          {"task_id": "old", "status": "discarded", "write_scope": ["obsolete/"]}]},
                  "trajectory": {"events": [judgment], "runtime_os_evidence": {"summary": {"reason": judgment}}},
                  "deterministic_checks": {"task_completion_rate": 1}, "correctness_signal": {"reason": judgment},
                  "current_artifacts": {"files": ["complete current artifact"], "review_basis": {"runtime_budget": {"limit": 8}},
                    "review_focus": {"criteria": [{"source_kind": "user_request", "text": "ANSWER must equal 42"},
                                                  {"source_kind": "model_proposal", "text": judgment}]}},
                  "cost_report": {"model_calls": 2}, "policy": {"permissions": {"allow_shell": False}}}
        before = json.dumps(source, sort_keys=True)
        view = tools.bind_evidence(source)
        assert judgment not in json.dumps(view)
        assert view["goal_spec"]["original_goal"] == source["goal_spec"]["original_goal"]
        assert view["goal_spec"]["edit_boundary"] == source["goal_spec"]["edit_boundary"]
        assert view["task_plan"]["tasks"] == [original_scope]
        for key in ["policy", "cost_report"]:
            assert view[key] == source[key]
        for key in ["files", "review_basis"]:
            assert view["current_artifacts"][key] == source["current_artifacts"][key]
        assert view["current_artifacts"]["review_focus"]["criteria"] == source["current_artifacts"]["review_focus"]["criteria"][:1]
        for key in ["goal_spec", "task_plan", "deterministic_checks", "correctness_signal"]:
            ref = view[key]["deferred_evidence_ref"]
            assert json.loads(tools.evidence.sections[ref]["content"]) == source[key]
        assert json.dumps(source, sort_keys=True) == before
        assert view["review_input_projection"]["runtime_normalization"] == "original_complete_context"
    tools.finish("completed")


@pytest.mark.parametrize("expression,valid", [("42", True), ("6 * 7", True), ("-(6 * 7)", False)])
def test_independent_check_accepts_equivalent_expression_and_rejects_real_defect(tmp_path, expression, valid):
    tools = setup(tmp_path, content=f"ANSWER = {expression}\n")

    class Model:
        turn = 0

        def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                payload = json.loads(request.messages[1].text())
                assert "INHERITED_UNQUALIFIED_PASS" not in json.dumps(payload)
                assert payload["current_artifacts"]["files"][0]["status"] == "complete"
                assert payload["current_artifacts"]["files"][0]["content"].splitlines() == [f"ANSWER = {expression}"]
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command("from answer import ANSWER; assert ANSWER == 42, 'value mismatch'")}}]})
            assert ("exited 0" if valid else "value mismatch") in request.messages[-1].text()
            return response({"overall": {"status": "pass" if valid else "fail", "score": int(valid), "reason": "Current value checked"}})

    source = {"goal_spec": {"original_goal": "ANSWER must equal 42; equivalent expressions are valid"},
              "current_artifacts": tools.artifacts,
              "trajectory": {"events": ["INHERITED_UNQUALIFIED_PASS"]},
              "deterministic_checks": {"task_completion_rate": 1}}
    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate(source, "run-review")
    assert report["overall"]["status"] == ("pass" if valid else "fail")
    assert report["trajectory_eval"]["review_validation"]["command_check_count"] == 1
    assert (tmp_path / "answer.py").read_text() == f"ANSWER = {expression}\n"


def test_review_machine_description_matches_execution_permissions_without_grant(tmp_path):
    tools = setup(tmp_path)
    snapshot(tools)
    def by_name():
        return {t["name"]: t for t in tools.describe()["tools"]}
    assert by_name()["run_tests"]["permission"] == "ask"
    assert "command" in by_name()["run_tests"]["parameter_contract"]
    assert "verification_ref" not in by_name()["run_tests"]["parameter_contract"]
    assert by_name()["inspect_evidence"]["permission"] == "allow"
    tools.context.policy["permissions"]["allow_shell"] = False
    assert by_name()["run_tests"]["permission"] == "deny"
    assert not invoke(tools, "run_tests", {"command": command("print('not authorized')")})[0].ok
    tools.finish("completed")


def test_review_reference_description_is_scoped_and_mixed_arguments_still_refused(tmp_path):
    from asteria_runtime.core.agent_tool_surface import model_tool_surface

    ordinary = next(t for t in model_tool_surface(["run_tests"], allow_shell=True) if t["name"] == "run_tests")
    assert "verification_ref" in ordinary["parameter_contract"]
    tools = setup(tmp_path)
    snapshot(tools)
    review = next(t for t in tools.describe()["tools"] if t["name"] == "run_tests")
    assert "verification_ref" not in review["parameter_contract"]
    refused = invoke(tools, "run_tests", {"command": command("print('not executed')"),
                                          "verification_ref": "unavailable"})[0]
    assert not refused.ok and "never both" in refused.summary
    assert refused.data.get("returncode") is None
    assert tools.context.budget.cost_report()["tool_calls"] == 0
    assert "verification_ref" in ordinary["parameter_contract"]
    tools.finish("completed")
