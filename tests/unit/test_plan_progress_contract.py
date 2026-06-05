from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.core.user_progress_view import (
    build_plan_completion_copy,
    build_plan_runtime_progress,
    build_user_progress_projections,
    latest_main_plan_event,
    required_main_transcript_kinds,
)
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.storage.schema_validator import SchemaValidator

from tests.integration.test_plan_command import FakePlanClient


def test_latest_main_plan_event_prefers_latest_main_plan(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    logger.record(
        run_id="run-1",
        channel="progress",
        phase="plan",
        status="running",
        title="制定计划",
        summary="正在拆解任务。",
        display_level="main",
        transcript_kind="plan",
    )
    logger.record(
        run_id="run-1",
        channel="progress",
        phase="plan",
        status="completed",
        title="计划已生成",
        summary="共 2 个任务。",
        display_level="main",
        transcript_kind="plan",
    )

    latest = latest_main_plan_event(logger.read_all())
    assert latest is not None
    assert latest["title"] == "计划已生成"
    assert latest["transcript_kind"] == "plan"


def test_build_plan_completion_copy_uses_chinese_summary() -> None:
    title, summary = build_plan_completion_copy(
        task_count=2,
        task_titles=["实现 CLI", "补充测试"],
        quality_status="pass",
        quality_score=0.91,
    )

    assert title == "计划已生成"
    assert "共 2 个任务" in summary
    assert "实现 CLI" in summary
    assert "补充测试" in summary
    assert "计划质量：良好" in summary


def test_status_json_exposes_plan_summary_after_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    payload = StatusCommand(tmp_path).run().to_dict()
    plan = payload["runtime_progress"]["plan"]

    assert plan is not None
    assert plan["transcript_kind"] == "plan"
    assert plan["title"] == "计划已生成"
    assert "共 2 个任务" in str(plan["summary"])
    assert plan["task_count"] == 2

    run_dirs = sorted((tmp_path / ".asteria" / "runs").iterdir(), key=lambda item: item.name)
    user_progress = [
        event
        for event in UserProgressLogger(
            run_dirs[-1] / "user_progress.jsonl",
            SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas"),
        ).read_all()
        if event.get("transcript_kind") == "plan" and event.get("display_level") == "main"
    ]
    assert user_progress
    assert user_progress[-1]["title"] == "计划已生成"
    assert build_plan_runtime_progress(user_progress[-1])["transcript_kind"] == "plan"


def test_user_progress_projections_extract_tool_verify_final(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "src" / "asteria_runtime" / "schemas")
    logger = UserProgressLogger(tmp_path / "user_progress.jsonl", validator)

    logger.record(
        run_id="run-1",
        channel="tool",
        phase="execute",
        status="running",
        title="正在使用 read_file",
        summary="读取文件。",
        display_level="main",
        transcript_kind="tool_use",
    )
    logger.validation_event(
        run_id="run-1",
        title="验证完成",
        summary="task-0001：1/1 项验证通过。",
        validation={"status": "passed", "passed": 1, "total": 1},
    )
    logger.final_report_event(
        run_id="run-1",
        title="结果已生成",
        summary="最终报告已写入。",
        final_report_path="final_report.md",
    )

    events = logger.read_all()
    projections = build_user_progress_projections(events)
    assert projections["tool"]["transcript_kind"] == "tool_use"
    assert projections["verify"]["transcript_kind"] == "verification"
    assert projections["final"]["transcript_kind"] == "final"
    assert required_main_transcript_kinds(events) >= {"tool_use", "verification", "final"}
