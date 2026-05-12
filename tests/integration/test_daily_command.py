from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_runtime.commands.daily_command import (
    DailyPlanCommand,
    DailyReportCommand,
    DailyRunCommand,
)
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


def _cost_report(model_calls: int = 0, tool_calls: int = 0, repair_attempts: int = 0) -> dict:
    return {
        "schema_version": "0.1.0",
        "run_id": "run-20260512-0001",
        "status": "within_budget",
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "strong_model_calls": model_calls,
        "cheap_model_calls": 0,
        "repair_attempts": repair_attempts,
        "context_compactions": 0,
        "user_decisions": 0,
        "warnings": [],
    }


def test_daily_plan_selects_failed_only_acceptance_action(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-12T00:00:00+08:00",
        "summary_json": str(tmp_path / ".agent" / "acceptance" / "latest_summary.json"),
        "scenarios": [
            {
                "scenario": "config_driven_report",
                "ok": False,
                "workspace": None,
                "failure_summary": "failed",
            }
        ],
    }
    JsonStore(validator).write(
        tmp_path / ".agent" / "acceptance" / "acceptance_report.json",
        report,
        "acceptance_report",
    )

    result = DailyPlanCommand(tmp_path, date="2026-05-12").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert result.action_count == 1
    assert plan["cycle_id"] == "2026-05-12"
    assert plan["schedule_type"] == "long_running_cycle"
    assert plan["actions"][0]["kind"] == "acceptance_failed_only"
    assert "--failed-only" in plan["actions"][0]["command"]
    validator.validate("daily_plan", plan)


def test_daily_run_plan_only_writes_report_and_markdown(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyRunCommand(
        tmp_path,
        date="release-hardening",
        objective="Advance the autonomous runtime until release gate readiness.",
    ).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.executed is False
    assert report["executed"] is False
    assert report["cycle_id"] == "release-hardening"
    assert report["schedule_type"] == "long_running_cycle"
    assert report["objective"] == "Advance the autonomous runtime until release gate readiness."
    assert report["goal"]
    assert report["progress"]["planned_actions"] == 1
    assert report["stop_reason"] == "plan_only"
    assert report["risks"]
    assert report["results"][0]["status"] == "planned"
    assert (result.report_path.with_suffix(".md")).exists()
    markdown = result.report_path.with_suffix(".md").read_text(encoding="utf-8")
    assert "## Budget" in markdown
    assert "## Risks" in markdown
    assert "release-hardening" in markdown
    SchemaValidator(Path.cwd() / "schemas").validate("daily_report", report)


def test_daily_report_creates_plan_only_report_when_missing(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyReportCommand(tmp_path, date="2026-05-12").run()

    assert result.report_path.exists()
    assert result.status == "planned"
    assert "planned but not executed" in result.summary


def test_daily_run_execute_records_evidence_and_budget_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".agent", validator)
    run = run_store.create_run("test")
    run_store.set_current_run(run["run_id"], "daily test")
    run_dir = tmp_path / ".agent" / "runs" / run["run_id"]
    store.write(run_dir / "cost_report.json", _cost_report(), "cost_report")

    def fake_run(*args, **kwargs):
        store.write(run_dir / "cost_report.json", _cost_report(2, 3, 1), "cost_report")
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DailyRunCommand(tmp_path, date="2026-05-12", execute=True).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert report["budget"]["model_calls"] == 2
    assert report["budget"]["tool_calls"] == 3
    assert report["budget"]["repair_attempts"] == 1
    assert report["results"][0]["evidence_path"]
    daily_evidence = tmp_path / ".agent" / "daily" / "2026-05-12" / "task_execution_evidence.jsonl"
    run_evidence = run_dir / "task_execution_evidence.jsonl"
    assert daily_evidence.exists()
    assert run_evidence.exists()
    evidence = json.loads(daily_evidence.read_text(encoding="utf-8").splitlines()[0])
    assert evidence["task"]["task_kind"] == "daily_action"
    assert evidence["status"] == "done"
    validator.validate("daily_report", report)


def test_daily_run_execute_stops_on_failure_and_reports_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="pending decision")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DailyRunCommand(tmp_path, date="2026-05-12", execute=True).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "blocked"
    assert report["stop_reason"] == "failure limit reached (1/1)"
    assert report["results"][0]["status"] == "fail"
    assert report["results"][0]["failure_type"] == "pending_decision"
    assert any("pending_decision" in risk for risk in report["risks"])


def test_daily_run_hard_stops_before_action_when_budget_is_exhausted(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyRunCommand(
        tmp_path,
        date="2026-05-12",
        execute=True,
        max_runtime_minutes=0,
    ).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "idle"
    assert report["results"] == []
    assert report["stop_reason"].startswith("runtime budget reached")
