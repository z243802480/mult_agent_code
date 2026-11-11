from copy import deepcopy
import json
from pathlib import Path

import pytest

from asteria_runtime.core.context_slimming import project_review_evidence, slim_review_context
from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.storage.schema_validator import SchemaValidator


@pytest.mark.parametrize("focused", [False, True])
def test_review_projection_retains_failures_and_only_removes_reconstructible_copies(focused):
    output = "traceback: genuine verification failure\n" * 400
    # This is the real renderer used to build persisted observations.
    from asteria_runtime.core.agent_harness import _model_facing_payload

    data = {
        "command": "python -m pytest",
        "requested_command": "python -m pytest",
        "stdout": output,
        "stderr": "failed assertion",
        "returncode": 1,
        "stdout_truncated": False,
    }
    row = {
        "observation_id": "obs-red",
        "tool_name": "run_tests",
        "ok": False,
        "summary": "tests failed",
        "observation": {
            "tool_name": "run_tests",
            "ok": False,
            "error": "nonzero_exit",
            "summary": "tests failed",
            "data": data,
            "payload": _model_facing_payload("run_tests", data),
        },
    }
    context = {
        "context_policy": {"mode": "focused" if focused else "slim"},
        "correctness_signal": {"status": "fail", "score": 0.0},
        "deterministic_checks": {"verification_pass_rate": 0.0},
        "tool_observations": [row],
        "trajectory": {"tool_observations": [deepcopy(row)]},
        "goal_spec": {"user_data": {"command": "keep", "requested_command": "keep"}},
    }
    before = deepcopy(context)
    projected = project_review_evidence(context)
    for rows in [projected["tool_observations"], projected["trajectory"]["tool_observations"]]:
        assert len(rows) == 1 and rows[0]["ok"] is False
        assert "summary" not in rows[0]
        obs = rows[0]["observation"]
        assert obs["summary"] == "tests failed" and obs["error"] == "nonzero_exit"
        assert obs["data"]["stdout"] == output and obs["data"]["returncode"] == 1
        assert obs["data"]["requested_command"] == "python -m pytest"
        assert "command" not in obs["data"] and "payload" not in obs
    assert projected["goal_spec"] == before["goal_spec"]
    assert projected["correctness_signal"] == before["correctness_signal"]
    assert projected["deterministic_checks"] == before["deterministic_checks"]
    assert context == before


def test_review_projection_keeps_unique_payload_read_file_bytes_and_different_commands():
    rows = [
        {"summary": "outer detail", "observation": {
            "tool_name": "run_command", "summary": "inner detail", "ok": False,
            "data": {"command": "actual", "requested_command": "requested", "stdout": "raw"},
            "payload": "unique diagnostic, not derivable from stdout",
        }},
        {"observation": {"tool_name": "read_file", "summary": "read source",
                         "data": {"path": "source.py"}, "payload": "1\tSOURCE_BYTES"}},
    ]
    context = {"tool_observations": rows}
    projected = project_review_evidence(context)
    assert projected["tool_observations"] == rows


@pytest.mark.parametrize("signal", [None, {"status": "fail", "score": 0.0, "reason": "fresh failure"}])
def test_actual_review_request_preserves_missing_or_failed_verification(signal):
    requests = []

    class UnavailableModel:
        def chat(self, request):
            requests.append(request)
            raise RuntimeError("offline fixture")

    context = {
        "deterministic_checks": {
            "task_completion_rate": 1.0,
            "blocked_task_count": 0,
            "verification_pass_rate": 0.0,
        },
        "cost_report": {"status": "within_budget"},
        "correctness_signal": signal,
        "review_model_fallback_tiers": ["strong"],
        "tool_observations": [{"observation": {
            "tool_name": "run_tests", "ok": False, "error": "nonzero_exit",
            "data": {"command": "old check", "requested_command": "old check", "returncode": 1},
        }}],
    }
    before = deepcopy(context)
    agent = ReviewAgent(UnavailableModel(), SchemaValidator(Path("schemas")))
    expected = agent._normalize({}, context, "run-check")["overall"]
    report = agent.evaluate(context, "run-check")
    assert len(requests) == 1
    payload = json.loads(requests[0].messages[-1].content)
    assert payload["tool_observations"][0]["observation"]["data"]["returncode"] == 1
    assert payload["correctness_signal"] == signal
    assert report["overall"]["status"] == expected["status"]
    assert report["overall"]["score"] == expected["score"]
    if signal is None:
        assert report["overall"]["score"] is None
        assert "unverified" in report["overall"]["reason"].lower()
    else:
        assert report["overall"]["status"] == "fail"
    assert context == before


def test_slim_review_context_keeps_recent_evidence_and_records_omissions() -> None:
    context = {
        "goal_spec": {
            "original_goal": "Create a local file",
            "target_outputs": ["result.json"],
        },
        "task_plan": {"tasks": [{"expected_artifacts": ["result.json"]}]},
        "trajectory": {
            "events": [{"event_id": f"event-{index}"} for index in range(12)],
            "tool_calls": [{"tool_call_id": f"tool-{index}"} for index in range(11)],
            "model_calls": [{"model_call_id": f"model-{index}"} for index in range(6)],
            "runtime_os_evidence": {
                "task_execution_evidence": [
                    {"evidence_id": f"evidence-{index}"} for index in range(9)
                ],
                "worker_results": [
                    {"worker_result_id": f"worker-{index}"} for index in range(7)
                ],
                "summary": {"worker_result_count": 7},
            },
        },
    }

    slimmed = slim_review_context(context)

    assert slimmed["context_policy"]["mode"] == "slim"
    assert slimmed["context_policy"]["fast_path"]["task_kind"] == "simple_file"
    assert [item["event_id"] for item in slimmed["trajectory"]["events"]] == [
        f"event-{index}" for index in range(4, 12)
    ]
    assert len(slimmed["trajectory"]["tool_calls"]) == 8
    assert len(slimmed["trajectory"]["model_calls"]) == 3
    assert len(
        slimmed["trajectory"]["runtime_os_evidence"]["task_execution_evidence"]
    ) == 5
    raw_refs = slimmed["trajectory"]["raw_evidence_refs"]
    assert raw_refs["events"] == {"total": 12, "kept": 8, "omitted": 4}
    assert raw_refs["runtime_os_evidence"]["worker_results"] == {
        "total": 7,
        "kept": 5,
        "omitted": 2,
    }
    assert context["trajectory"]["events"][0]["event_id"] == "event-0"


def test_slim_review_context_keeps_focused_mode_for_high_risk() -> None:
    context = {
        "goal_spec": {
            "original_goal": "Fix auth permission handling and deploy to production.",
            "target_outputs": ["src/auth.py"],
        },
        "task_plan": {"tasks": [{"expected_artifacts": ["src/auth.py"]}]},
        "trajectory": {"events": [{"event_id": f"event-{index}"} for index in range(12)]},
    }

    focused = slim_review_context(context)

    assert focused["context_policy"]["mode"] == "focused"
    assert focused["context_policy"]["fast_path"]["task_kind"] == "high_risk"
    assert len(focused["trajectory"]["events"]) == 12
    assert "raw_evidence_refs" not in focused["trajectory"]
