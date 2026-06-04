from pathlib import Path

from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


def test_user_progress_logger_writes_schema_validated_events(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator, session_id="session-1")

    event = logger.record(
        run_id="run-1",
        channel="model",
        event_type="delta",
        phase="plan",
        status="running",
        title="制定计划",
        summary="正在拆解任务。",
        content_delta="第一步确认目标。",
        artifact_refs=["task_plan.json"],
        call_chain=["PlanCommand", "GoalSpecAgent"],
        execution_chain=["goal_spec"],
    )

    assert event["event_id"] == "upe-0001"
    assert event["sequence"] == 1
    assert event["channel"] == "model"
    assert event["event_type"] == "delta"
    assert event["session_id"] == "session-1"
    assert event["call_chain"] == ["PlanCommand", "GoalSpecAgent"]
    assert event["transcript_kind"] == "plan"
    assert event["ui_intent"] == "work_progress"
    assert event["actions"] == []
    assert logger.read_all()[0]["phase"] == "plan"


def test_user_progress_logger_has_convenience_event_channels(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    logger.heartbeat(run_id="run-1", phase="execute", title="still running", summary="tool active")
    logger.artifact_event(
        run_id="run-1",
        title="artifact",
        summary="created plan",
        artifact_refs=["task_plan.json"],
    )
    logger.conclusion(run_id="run-1", phase="result", title="done", summary="complete")
    logger.workspace_event(
        run_id="run-1",
        title="workspace",
        summary="selected",
        workspace={"workspace_root": str(tmp_path), "permission_mode": "reviewed_auto"},
    )
    logger.permission_event(
        run_id="run-1",
        title="permission",
        summary="mode selected",
        permission={"mode": "reviewed_auto"},
    )
    logger.decision_event(
        run_id="run-1",
        title="decision",
        summary="selected",
        decision={"decision_id": "decision-0001", "effect": "task_created"},
    )
    logger.model_decision_event(
        run_id="run-1",
        title="model",
        summary="selected strong",
        model_selection={"selected_tier": "strong", "reason": "risk"},
    )
    logger.file_change_event(
        run_id="run-1",
        title="files",
        summary="changed",
        file_changes=[{"path": "src/app.py", "operation": "modified"}],
    )
    logger.validation_event(
        run_id="run-1",
        title="validation",
        summary="passed",
        validation={"status": "passed", "passed": 1, "total": 1},
    )
    logger.final_report_event(
        run_id="run-1",
        title="final",
        summary="written",
        final_report_path="final_report.md",
        final_report_summary_path="final_report_summary.json",
    )

    events = logger.read_all()
    assert [event["channel"] for event in events] == [
        "diagnostic",
        "evidence",
        "conclusion",
        "workspace",
        "permission",
        "progress",
        "model",
        "file",
        "validation",
        "conclusion",
    ]
    assert [event["event_type"] for event in events] == [
        "heartbeat",
        "evidence",
        "message",
        "workspace_selected",
        "permission_decision",
        "decision",
        "model_decision",
        "file_changed",
        "validation_result",
        "final_report",
    ]
    assert events[0]["display_level"] == "inspector"
    assert events[0]["transcript_kind"] == "diagnostic"
    assert events[5]["transcript_kind"] == "decision_request"
    assert events[6]["display_level"] == "inspector"
    assert events[6]["transcript_kind"] == "diagnostic"
    assert events[6]["ui_intent"] == "inform"
    assert events[7]["transcript_kind"] == "file_change"
    assert events[8]["transcript_kind"] == "verification"
    assert events[-1]["transcript_kind"] == "final"
    assert events[-1]["data"]["final_report_path"] == "final_report.md"


def test_user_progress_main_events_use_user_facing_copy(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    event = logger.record(
        run_id="run-1",
        channel="progress",
        event_type="message",
        phase="next",
        status="blocked",
        title="provider route blocked",
        summary="Run model-check before retrying gate-status.",
        content_delta="provider route blocked: model-check",
        display_level="main",
    )

    visible = "\n".join([event["title"], event["summary"], event["content_delta"]])
    assert "provider route blocked" not in visible
    assert "model-check" not in visible
    assert "gate-status" not in visible
    assert "model connection interrupted" in visible.lower()
    assert event["transcript_kind"] == "progress"
    assert event["ui_intent"] == "needs_attention"
    assert event["actions"] == [
        {
            "kind": "connection_check",
            "label": "Check connection",
            "command": "model-check --tier medium",
        },
        {
            "kind": "continue",
            "label": "Retry run",
            "command": "run --resume",
        },
    ]


def test_user_progress_blocked_phase_becomes_user_decision_request(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    event = logger.record(
        run_id="run-1",
        channel="progress",
        event_type="message",
        phase="blocked",
        status="blocked",
        title="Needs a decision",
        summary="Decision decision-0001 is waiting for input.",
        data={"decision_id": "decision-0001"},
    )

    assert event["transcript_kind"] == "ask"
    assert event["ui_intent"] == "needs_attention"
    assert event["actions"] == [
        {
            "kind": "decision",
            "label": "Decide",
            "command": "decide --list",
        }
    ]


def test_user_progress_repairs_corrupt_main_copy_at_runtime_boundary(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    event = logger.record(
        run_id="run-1",
        channel="progress",
        event_type="message",
        phase="review",
        status="completed",
        title="corrupt € review copy",
        summary="corrupt copy with backend mojibake marker 锛",
        transcript_kind="verification",
    )

    visible = "\n".join([event["title"], event["summary"], event["content_delta"]])
    assert "€" not in visible
    assert "锛" not in visible
    assert event["title"] == "Verification updated"
    assert event["transcript_kind"] == "verification"
    assert event["ui_intent"] == "work_progress"
