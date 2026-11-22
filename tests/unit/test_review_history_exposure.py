from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.observation_receipt import observation_receipt
from asteria_runtime.core.review_tools import ReviewTools
from test_review_tools import setup, invoke

F = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "benchmarks/review_cases/history_claims.py")
)


def evidence():
    statement = F["POSITIVE_CLAIM"]
    section = {
        "evidence_ref": "snapshot/trajectory.events",
        "content": "prefix " + statement + " suffix",
    }
    observed = ToolObservation(
        tool_name="inspect_evidence",
        ok=True,
        status="success",
        summary="page",
        payload=statement,
        data={
            "tool_call_id": "call-page",
            "evidence_ref": section["evidence_ref"],
            "source_snapshot_id": "snapshot",
            "offset": 0,
            "content": section["content"],
        },
    )

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    link = {
        "tool_call_id": "call-page",
        "tool_name": "inspect_evidence",
        "payload_included": True,
        "payload_sha256": hashlib.sha256(statement.encode()).hexdigest(),
        "receipt_sha256": digest(observation_receipt(observed)),
    }
    row = {
        "run_id": "run",
        "task_id": "review",
        "observation_id": "obs",
        "tool_call_id": "call-page",
        "tool_name": "inspect_evidence",
        "ok": True,
        "observation": dict(observed.__dict__),
    }
    start = {
        "run_id": "run",
        "task_id": "review",
        "purpose": "run_review",
        "request_attempt_id": "attempt",
        "messages_sha256": "a" * 64,
    }
    model = {
        **start,
        "model_call_id": "model",
        "input_evidence": {
            "status": "matched",
            "messages_sha256": "a" * 64,
            "assembly_messages_sha256": "a" * 64,
            "observations": [link],
        },
    }
    tap = {
        **start,
        "claim_sha256": hashlib.sha256(statement.encode()).hexdigest(),
        "matching_user_message_indices": [3],
    }
    return {
        "run_id": "run",
        "task_id": "review",
        "snapshot_id": "snapshot",
        "statement": statement,
        "section": section,
        "observations": [row],
        "models": [model],
        "prepared": [start],
        "taps": [tap],
    }


def test_complete_page_and_native_request_identity_establish_feedback_assembly():
    result = F["exposure"](**evidence())
    assert result["state"] == "feedback_assembled"
    assert result["page_call_ids"] == ["call-page"] and result["feedback_request_ids"] == ["model"]


@pytest.mark.parametrize(
    "change,expected",
    [
        ("no-read", "deferred_only"),
        ("other-page", "deferred_only"),
        ("wrong-run", "deferred_only"),
        ("wrong-task", "deferred_only"),
        ("wrong-ref", "deferred_only"),
        ("wrong-snapshot", "deferred_only"),
        ("duplicate-observation", "deferred_only"),
        ("forged-page", "deferred_only"),
        ("short-page", "deferred_only"),
        ("payload-omitted", "page_read_only"),
        ("hash-mismatch", "page_read_only"),
        ("missing-tap", "page_read_only"),
        ("missing-prepared", "page_read_only"),
        ("duplicate-prepared", "page_read_only"),
        ("tap-hash-mismatch", "page_read_only"),
        ("duplicate-link", "page_read_only"),
    ],
)
def test_reference_or_partial_or_ambiguous_evidence_is_not_full_exposure(change, expected):
    data = evidence()
    row = data["observations"][0]
    if change == "no-read":
        data["observations"] = []
    elif change == "other-page":
        row["observation"]["data"].update(offset=0, content="prefix ")
    elif change == "wrong-run":
        row["run_id"] = "foreign"
    elif change == "wrong-task":
        row["task_id"] = "other"
    elif change == "wrong-ref":
        row["observation"]["data"]["evidence_ref"] = "snapshot/another"
    elif change == "wrong-snapshot":
        row["observation"]["data"]["source_snapshot_id"] = "other"
    elif change == "duplicate-observation":
        data["observations"].append(deepcopy(row))
    elif change == "forged-page":
        row["observation"]["data"]["content"] = data["statement"] + " invented"
    elif change == "short-page":
        row["observation"]["data"]["content"] = "prefix " + data["statement"][:-1]
    elif change == "payload-omitted":
        data["models"][0]["input_evidence"]["observations"][0]["payload_included"] = False
    elif change == "hash-mismatch":
        data["models"][0]["input_evidence"]["observations"][0]["payload_sha256"] = "b" * 64
    elif change == "missing-tap":
        data["taps"] = []
    elif change == "missing-prepared":
        data["prepared"] = []
    elif change == "duplicate-prepared":
        data["prepared"].append(deepcopy(data["prepared"][0]))
    elif change == "tap-hash-mismatch":
        data["taps"][0]["messages_sha256"] = "b" * 64
    elif change == "duplicate-link":
        data["models"][0]["input_evidence"]["observations"] *= 2
    assert F["exposure"](**data)["state"] == expected


def test_inline_presence_also_requires_matching_native_preparation_and_request_hash():
    data = evidence()
    data["section"] = None
    data["observations"] = []
    data["taps"][0]["matching_user_message_indices"] = [1]
    assert F["exposure"](**data)["state"] == "inline_assembled"
    data["taps"][0]["claim_sha256"] = "wrong"
    assert F["exposure"](**data)["state"] == "not_available"


def test_boolean_message_position_is_not_an_inline_message_index():
    data = evidence()
    data["taps"][0]["matching_user_message_indices"] = [True]
    assert F["exposure"](**data)["state"] == "page_read_only"


@pytest.mark.parametrize("case", list(F["CASES"]))
def test_history_statements_defer_without_modifying_authority_and_can_be_read(tmp_path, case):
    tools = setup(tmp_path)
    statement = F["CASES"][case]["statement"]
    context = {
        "goal_spec": {"original_goal": "Keep the original request"},
        "trajectory": {
            "events": [
                {
                    "actor": "diagnostic_controller",
                    "summary": statement,
                    "data": {"fixture": True, "claim_authority": "unverified"},
                }
            ]
        },
        "current_artifacts": {"files": [{"path": "answer.py", "content": "ANSWER = 41"}]},
    }
    before = deepcopy(context)
    view = tools.bind_evidence(context)
    assert statement not in json.dumps(view) and context == before
    assert view["goal_spec"]["original_goal"] == context["goal_spec"]["original_goal"]
    ref = view["trajectory"]["events"]["deferred_evidence_ref"]
    assert statement in invoke(tools, "inspect_evidence", {"evidence_ref": ref})[0].payload
    tools.finish("completed")


def test_strict_profile_keeps_original_context_without_granting_a_read_tool(tmp_path):
    tools = setup(tmp_path)
    tools.context.policy["permission_mode"] = "ask_everything"
    tools = ReviewTools(tools.context, tools.artifacts, tools.goal, tools.board)
    context = {"trajectory": {"events": [{"summary": F["POSITIVE_CLAIM"]}]}}
    assert tools.bind_evidence(context) == context
    assert tools.evidence is None
    assert tools.describe()["tools"] == []
    assert not invoke(tools, "inspect_evidence", {"evidence_ref": "anything"})[0].ok
    assert tools.finish("completed")["errors"]
