from asteria_runtime.core.context_slimming import slim_review_context


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
