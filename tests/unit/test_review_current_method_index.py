"""Declared method discovery and observation identity stay scoped to their task."""
from copy import deepcopy
import json

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.core.review_evidence import ReviewEvidence
from tests.unit.test_review_tools import setup, response, command


def task(task_id, cmd, status="done"):
    return {"task_id": task_id, "status": status, "validation_commands": [cmd]}


def row(tools, task_id, call_id, cmd, code):
    return {"run_id": tools.context.run_id, "task_id": task_id, "tool_call_id": call_id,
            "observation_id": "obs-" + call_id, "tool_name": "run_tests", "ok": code == 0,
            "status": "success" if code == 0 else "failure", "observation": {
                "dispatch_state": "dispatched", "data": {"requested_command": cmd, "returncode": code}}}


def bind(tools, tasks, observations, source=None):
    calls = [{k: o[k] for k in ("run_id", "task_id", "tool_call_id", "tool_name")}
             | {"agent_id": "CoderAgent"} for o in observations]
    evidence = ReviewEvidence(tools.context, tools.artifacts["evidence_id"], tools.task["task_id"],
                              source or {}, observations, calls, {"tasks": tasks})
    tools.evidence = evidence
    return evidence, evidence.input_view()["review_evidence"]["verification_methods"]


def test_initial_index_identifies_command_source_and_raw_observation_without_inheriting_verdict(tmp_path):
    tools = setup(tmp_path)
    cmd = command("print('a bounded observation')")
    source = {"trajectory": {"events": ["INHERITED_VERDICT"]},
              "goal_spec": {"original_goal": "Deliver an answer equal to 42"}}
    before = deepcopy(source)
    evidence, methods = bind(tools, [task("active", cmd)], [row(tools, "active", "c", cmd, 0)], source)
    entry = methods["current"][0]
    assert entry["task_id"] == "active" and entry["command_excerpt"] == cmd
    assert entry["source_ref"] == "task_plan.tasks[0].validation_commands[0]"
    observed = entry["latest_observation"]
    assert observed["tool_call_id"] == "c" and observed["returncode"] == 0
    assert observed["recorded_executor"] == "CoderAgent"
    assert observed["dispatch_state"] == "dispatched"
    assert observed["artifact_binding"] == "historical_execution_not_bound_to_this_review_snapshot"
    assert entry["requirement_coverage"] == "unassessed"
    assert "INHERITED_VERDICT" not in json.dumps(evidence.input_view())
    assert source == before
    tools.finish("completed")


def test_current_failure_does_not_borrow_later_discarded_task_success(tmp_path):
    tools = setup(tmp_path)
    cmd = "check the delivered value"
    evidence, methods = bind(tools, [task("current", cmd), task("old", cmd, "discarded")],
                             [row(tools, "current", "failed", cmd, 1), row(tools, "old", "green", cmd, 0)])
    entry = methods["current"][0]
    assert entry["observation_ref"].endswith("/observation/failed")
    assert entry["latest_observation"]["returncode"] == 1
    detail = json.loads(evidence.sections[entry["method_ref"]]["content"])
    assert [r["task_id"] for r in detail["observations"]] == ["current"]
    tools.finish("completed")


def test_same_command_in_two_current_tasks_has_separate_observation_bindings(tmp_path):
    tools = setup(tmp_path)
    cmd = "same original bytes"
    evidence, methods = bind(tools, [task("a", cmd), task("b", cmd)],
                             [row(tools, "a", "bad", cmd, 1), row(tools, "b", "good", cmd, 0)])
    entries = {e["task_id"]: e for e in methods["current"]}
    assert entries["a"]["method_ref"] != entries["b"]["method_ref"]
    assert entries["a"]["latest_observation"]["returncode"] == 1
    assert entries["b"]["latest_observation"]["returncode"] == 0
    for identity, entry in entries.items():
        assert all(r["task_id"] == identity for r in json.loads(evidence.sections[entry["method_ref"]]["content"])["observations"])
    tools.finish("completed")


@pytest.mark.parametrize("case", ["missing", "foreign_run", "other_task", "ambiguous_call"])
def test_unobserved_current_declaration_is_visible_without_fabricating_execution(tmp_path, case):
    tools = setup(tmp_path)
    cmd = "unexecuted required check"
    observed = row(tools, "current", "c", cmd, 0)
    observations = [] if case == "missing" else [observed]
    if case == "foreign_run":
        observed["run_id"] = "other-run"
    if case == "other_task":
        observed["task_id"] = "other-task"
    if case == "ambiguous_call":
        observations.append(deepcopy(observed))
    evidence, methods = bind(tools, [task("current", cmd)], observations)
    entry = methods["current"][0]
    assert entry["command_excerpt"] == cmd
    assert entry["latest_observation"] is None and entry["observation_ref"] is None
    assert json.loads(evidence.sections[entry["method_ref"]]["content"])["observations"] == []
    assert entry["requirement_coverage"] == "unassessed"
    tools.finish("completed")


def test_inline_index_and_persisted_declared_index_are_bounded_and_omissions_visible(tmp_path):
    tools = setup(tmp_path)
    current = task("current", "")
    current["validation_commands"] = [f"check {i}" for i in range(90)]
    evidence, methods = bind(tools, [current], [])
    assert len(methods["current"]) == 8 and methods["omitted_current"] == 82
    all_current = json.loads(evidence.sections[methods["all_current_methods_ref"]]["content"])
    assert len(all_current["methods"]) == 64 and all_current["omitted_methods"] == 26
    assert sum(s["stored_characters"] for s in evidence.sections.values()) <= 1_048_576
    tools.finish("completed")


def test_duplicate_declarations_share_first_exact_source_without_conflicting_references(tmp_path):
    tools = setup(tmp_path)
    current = task("current", "check")
    current["validation_commands"] *= 2
    evidence, methods = bind(tools, [current], [])
    assert len(methods["current"]) == 1
    entry = methods["current"][0]
    assert json.loads(evidence.sections[entry["method_ref"]]["content"])["source_ref"] == entry["source_ref"]
    tools.finish("completed")


def test_ambiguous_task_identity_cannot_claim_an_observation_binding(tmp_path):
    tools = setup(tmp_path)
    _, methods = bind(tools, [task("same", "check"), task("same", "check", "discarded")],
                       [row(tools, "same", "c", "check", 0)])
    assert methods["current"] == [] and methods["ambiguous_tasks"] == 1
    tools.finish("completed")


def test_observation_outside_window_is_not_reported_as_never_executed(tmp_path, monkeypatch):
    import asteria_runtime.core.review_evidence as module
    monkeypatch.setattr(module, "MAX_INDEX_ROWS", 2)
    tools = setup(tmp_path)
    observations = [row(tools, "current", "old", "check", 0)]
    for i in range(2):
        observations.append({**row(tools, "current", f"read-{i}", "", 0), "tool_name": "read_file"})
    evidence, methods = bind(tools, [task("current", "check")], observations)
    entry = methods["current"][0]
    assert entry["latest_observation"] is None
    assert entry["observation_availability"] == "no_unambiguous_observation_in_bounded_snapshot"
    assert evidence.origins["record_count"] == 1
    tools.finish("completed")


@pytest.mark.parametrize("expression,valid", [("42", True), ("6 * 7", True), ("41", False)])
def test_current_method_data_reaches_review_and_actual_check_accepts_equivalent_or_rejects_defect(tmp_path, expression, valid):
    tools = setup(tmp_path, content=f"ANSWER = {expression}\n")
    cmd = command("from answer import ANSWER; assert ANSWER == 42, 'current value mismatch'; print('current value checked')")
    evidence, _ = bind(tools, [task("current", cmd)], [row(tools, "current", "historic", cmd, 0)],
                       {"current_artifacts": tools.artifacts,
                        "goal_spec": {"original_goal": "ANSWER must equal 42; equivalent expressions are valid"}})
    tools.bind_evidence = lambda context: evidence.input_view()

    class Model:
        turn = 0
        def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                entry = json.loads(request.messages[1].text())["review_evidence"]["verification_methods"]["current"][0]
                assert entry["command_excerpt"] == cmd
                assert entry["latest_observation"]["returncode"] == 0
                assert entry["requirement_coverage"] == "unassessed"
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {"command": cmd}}]})
            assert ("exited 0" if valid else "current value mismatch") in request.messages[-1].text()
            return response({"overall": {"status": "pass" if valid else "fail", "reason": "Current value checked"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, tools.context.run_id)
    assert report["overall"]["status"] == ("pass" if valid else "fail")
    assert report["trajectory_eval"]["review_validation"]["command_check_count"] == 1
    assert (tmp_path / "answer.py").read_text() == f"ANSWER = {expression}\n"
