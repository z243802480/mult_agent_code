import json
from pathlib import Path

from asteria_runtime.commands.brainstorm_command import BrainstormCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.models.fake import FakeModelClient


def test_brainstorm_command_writes_report_without_applying(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = BrainstormCommand(
        tmp_path,
        goal="create an offline artifact",
        model_client=FakeModelClient(),
    ).run()

    assert result.candidate_count == 1
    assert result.created_tasks == 0
    assert result.created_decisions == 0
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["recommendation"]["candidate_id"] == "candidate-0001"
    assert result.markdown_path.exists()
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["title"] == "开始头脑风暴" for event in user_progress)
    assert any(
        event["channel"] == "evidence"
        and event["title"] == "头脑风暴报告已写入"
        for event in user_progress
    )
    assert any(event["title"] == "头脑风暴完成" for event in user_progress)


def test_brainstorm_command_apply_creates_tasks_and_decisions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = BrainstormCommand(
        tmp_path,
        goal="create an offline artifact",
        apply=True,
        model_client=FakeModelClient(),
    ).run()

    assert result.created_tasks == 1
    assert result.created_decisions == 1
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    cost = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))

    assert task_plan["tasks"][0]["status"] == "ready"
    assert task_plan["tasks"][0]["expected_artifacts"] == ["offline_artifact.txt"]
    assert decisions[0]["status"] == "pending"
    assert run["status"] == "paused"
    assert run["current_phase"] == "DECIDE"
    assert cost["model_calls"] == 1
    assert cost["user_decisions"] == 1
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["title"] == "头脑风暴结果已应用"
        and event["data"]["created_tasks"] == 1
        and event["data"]["created_decisions"] == 1
        for event in user_progress
    )
    assert any(event["event_type"] == "decision" for event in user_progress)
