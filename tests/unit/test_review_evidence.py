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


def test_no_tools_retains_original_context_and_small_history_stays_inline(tmp_path):
    tools = setup(tmp_path)
    source = {"trajectory": {"events": ["small"]}}
    assert tools.bind_evidence(source)["trajectory"] == source["trajectory"]
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
        {"trajectory": {"events": ["unique-original" * 2000]}}, "run-review")
    assert report["overall"]["status"] == "fail"
    assert report["goal_eval"]["requirement_coverage"] == 0.8
    assert report["goal_eval"]["requirement_coverage_source"] == "model_assessment"
    assert report["goal_eval"]["requirement_coverage_runtime_verified"] is False
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


def test_review_machine_description_matches_execution_permissions_without_grant(tmp_path):
    tools = setup(tmp_path)
    snapshot(tools)
    def by_name():
        return {t["name"]: t for t in tools.describe()["tools"]}
    assert by_name()["run_tests"]["permission"] == "ask"
    assert by_name()["inspect_evidence"]["permission"] == "allow"
    tools.context.policy["permissions"]["allow_shell"] = False
    assert by_name()["run_tests"]["permission"] == "deny"
    assert not invoke(tools, "run_tests", {"command": command("print('not authorized')")})[0].ok
    tools.finish("completed")
