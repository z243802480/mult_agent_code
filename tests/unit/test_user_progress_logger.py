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

    events = logger.read_all()
    assert [event["channel"] for event in events] == ["diagnostic", "evidence", "conclusion"]
    assert [event["event_type"] for event in events] == ["heartbeat", "evidence", "message"]
    assert events[0]["display_level"] == "inspector"
