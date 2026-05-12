from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.commands.daily_command import (
    DailyPlanCommand,
    DailyReportCommand,
    DailyRunCommand,
)
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


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
    assert plan["actions"][0]["kind"] == "acceptance_failed_only"
    assert "--failed-only" in plan["actions"][0]["command"]
    validator.validate("daily_plan", plan)


def test_daily_run_plan_only_writes_report_and_markdown(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyRunCommand(tmp_path, date="2026-05-12").run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.executed is False
    assert report["executed"] is False
    assert report["results"][0]["status"] == "planned"
    assert (result.report_path.with_suffix(".md")).exists()
    SchemaValidator(Path.cwd() / "schemas").validate("daily_report", report)


def test_daily_report_creates_plan_only_report_when_missing(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyReportCommand(tmp_path, date="2026-05-12").run()

    assert result.report_path.exists()
    assert result.status == "planned"
    assert "planned but not executed" in result.summary
