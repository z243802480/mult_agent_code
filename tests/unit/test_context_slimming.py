from asteria_runtime.core.context_slimming import slim_execution_context, slim_review_context


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


def test_slim_execution_context_trims_task_prompt_context_without_mutating_source() -> None:
    runtime_context = {
        "memory": [
            {"content": f"decision-{index} " + ("x" * 1500)}
            for index in range(7)
        ],
        "tool_observations": [{"id": f"obs-{index}"} for index in range(9)],
        "harness_observations": [{"id": f"harness-{index}"} for index in range(7)],
        "context_package": {
            "read_scope_files": [
                {"path": f"file-{index}.py", "content": "x" * 1500}
                for index in range(7)
            ],
            "recent_events": [{"id": f"event-{index}"} for index in range(8)],
            "context_envelope": {"payload": {"large": True}, "payload_hash": "sha256:ctx"},
        },
    }

    slimmed = slim_execution_context(
        runtime_context,
        task={"task_id": "task-1", "expected_artifacts": ["result.json"]},
        goal_spec={"original_goal": "Create a local file", "target_outputs": ["result.json"]},
    )

    assert slimmed["context_policy"]["mode"] == "slim"
    assert slimmed["context_policy"]["fast_path"]["task_kind"] == "simple_file"
    assert len(slimmed["tool_observations"]) == 5
    assert len(slimmed["memory"]) == 5
    assert slimmed["memory"][0]["content_truncated"] is True
    assert len(slimmed["harness_observations"]) == 5
    assert len(slimmed["context_package"]["read_scope_files"]) == 5
    assert slimmed["context_package"]["read_scope_files"][0]["content_truncated"] is True
    assert len(slimmed["context_package"]["read_scope_files"][0]["content"]) == 1200
    assert slimmed["raw_context_refs"]["context_package"]["read_scope_files"] == {
        "total": 7,
        "kept": 5,
        "omitted": 2,
    }
    assert len(runtime_context["context_package"]["read_scope_files"][0]["content"]) == 1500


def test_slim_execution_context_ignores_read_scope_for_bugfix_classification() -> None:
    slimmed = slim_execution_context(
        {"context_package": {"read_scope_files": []}},
        task={
            "task_id": "task-1",
            "task_kind": "diagnostic",
            "expected_artifacts": ["calc.py"],
            "expected_changed_files": ["calc.py"],
            "write_scope": ["calc.py"],
            "read_scope": ["AGENTS.md", "calc.py", "test_calc.py"],
        },
        goal_spec={
            "original_goal": "Fix calc.py so add(2, 3) returns 5 while preserving tests.",
            "target_outputs": ["calc.py"],
        },
    )

    assert slimmed["context_policy"]["mode"] == "slim"
    assert slimmed["context_policy"]["fast_path"]["task_kind"] == "single_file_bugfix"
