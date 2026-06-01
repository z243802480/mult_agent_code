from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.roadmap_command import RoadmapCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_roadmap_update_generates_json_and_markdown_from_weekly_report(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    reports_dir = tmp_path / ".asteria" / "reports"
    reports_dir.mkdir(parents=True)
    store.write(
        reports_dir / "weekly_report_2026-W20.json",
        {
            "schema_version": "0.1.0",
            "week_id": "2026-W20",
            "root": str(tmp_path),
            "created_at": "2026-05-12T10:00:00+08:00",
            "status": "blocked",
            "summary": "1 long-run cycle, 1 risk.",
            "long_run": {"cycles": 1},
            "acceptance": {
                "runs": 1,
                "latest_ok": False,
                "latest_suite": "core",
                "latest_total": 1,
                "latest_failed": 1,
                "failed_scenarios": ["config_driven_report"],
            },
            "model_profile": {
                "status": "ready",
                "profile_count": 1,
                "weak_routes": [],
            },
            "usage_signals": {
                "status": "needs_attention",
                "unresolved": 1,
            },
            "usage_signal_analysis": {
                "status": "needs_attention",
                "roadmap_tasks": [
                    {
                        "task_id": "ops-usage-unresolved-artifacts",
                        "title": "Resolve unresolved artifact outcomes before widening dogfooding.",
                        "priority": "P0",
                    }
                ],
            },
            "risks": ["Acceptance failures remain: config_driven_report"],
            "next_actions": ["Run failed-only acceptance."],
        },
        "weekly_report",
    )

    result = RoadmapCommand(tmp_path).run()

    roadmap = store.read(result.roadmap_path, "project_roadmap")
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert result.status == "blocked"
    assert roadmap["source_reports"]["weekly_report"].endswith("weekly_report_2026-W20.json")
    assert roadmap["milestones"][1]["status"] == "blocked"
    assert "Run failed-only acceptance." in roadmap["next_actions"]
    assert any("Resolve unresolved artifact outcomes" in item for item in roadmap["next_actions"])
    assert roadmap["source_reports"]["usage_signal_analysis_status"] == "needs_attention"
    assert "自动路线图" in markdown
    assert "config_driven_report" in markdown


def test_roadmap_update_works_without_weekly_report(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = RoadmapCommand(tmp_path).run()

    roadmap = JsonStore(SchemaValidator(Path.cwd() / "schemas")).read(
        result.roadmap_path,
        "project_roadmap",
    )
    assert result.status == "on_track"
    assert roadmap["source_reports"]["weekly_report"] is None
    assert "daily-plan" in roadmap["next_actions"][0]
