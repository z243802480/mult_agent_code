from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.weekly_report_command import WeeklyReportCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_weekly_report_summarizes_long_run_acceptance_and_model_profile(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    agent_dir = tmp_path / ".agent"
    daily_dir = agent_dir / "daily" / "release-hardening"
    daily_dir.mkdir(parents=True)
    store.write(
        daily_dir / "daily_report.json",
        {
            "schema_version": "0.1.0",
            "date": "release-hardening",
            "cycle_id": "release-hardening",
            "schedule_type": "long_running_cycle",
            "root": str(tmp_path),
            "status": "blocked",
            "created_at": "2026-05-12T10:00:00+08:00",
            "plan_path": str(daily_dir / "daily_plan.json"),
            "executed": True,
            "goal": "Stabilize release gate",
            "objective": "Stabilize release gate",
            "progress": {
                "planned_actions": 1,
                "attempted_actions": 1,
                "completed_actions": 0,
                "failed_actions": 1,
            },
            "stop_reason": "failure limit reached (1/1)",
            "budget": {},
            "results": [],
            "summary": "Executed 1 action(s), 0 passed.",
            "risks": ["Acceptance still has failing scenarios: config_driven_report"],
            "model_profile": {"status": "ready", "profile_count": 1},
            "next_actions": ["Run failed-only acceptance."],
        },
        "daily_report",
    )
    acceptance_dir = agent_dir / "acceptance"
    acceptance_dir.mkdir(parents=True)
    acceptance = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-12T10:01:00+08:00",
        "summary_json": str(acceptance_dir / "latest_summary.json"),
        "aggregate": {"total": 1, "passed": 0, "failed": 1},
        "scenarios": [
            {
                "scenario": "config_driven_report",
                "capability": "configuration_change",
                "tier": "core",
                "ok": False,
                "workspace": None,
                "failure_summary": "report.md was not created",
            }
        ],
    }
    store.write(acceptance_dir / "acceptance_report.json", acceptance, "acceptance_report")
    jsonl.append(acceptance_dir / "history.jsonl", acceptance)
    model_dir = agent_dir / "model"
    model_dir.mkdir(parents=True)
    store.write(
        model_dir / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                    "total_calls": 3,
                    "success_calls": 1,
                    "failure_calls": 2,
                    "success_rate": 0.3333,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "average_input_tokens": 33.33,
                    "average_output_tokens": 16.67,
                    "failure_types": {"provider_response": 2},
                    "recommended_action": "use_json_stricter_or_switch_model",
                    "recent_failures": ["invalid JSON"],
                }
            ],
        },
        "model_capability_profile",
    )

    result = WeeklyReportCommand(tmp_path, week_id="2026-W20").run()

    report = store.read(result.report_path, "weekly_report")
    markdown = result.report_path.with_suffix(".md").read_text(encoding="utf-8")
    assert result.status == "blocked"
    assert report["long_run"]["cycles"] == 1
    assert report["long_run"]["failed_actions"] == 1
    assert report["acceptance"]["latest_failed"] == 1
    assert report["model_profile"]["weak_routes"][0]["purpose"] == "task_execution"
    assert any("Acceptance failures remain" in risk for risk in report["risks"])
    assert "agent /acceptance --failed-only --promote-failures" in report["next_actions"][0]
    assert "Weekly Production Report" in markdown
    assert "config_driven_report" in markdown


def test_weekly_report_handles_missing_inputs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = WeeklyReportCommand(tmp_path, week_id="2026-W20").run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "needs_attention"
    assert report["long_run"]["cycles"] == 0
    assert "No long-run cycle reports were found" in report["risks"][0]
    assert "agent /long-run-plan" in report["next_actions"][0]
