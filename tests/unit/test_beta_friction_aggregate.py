from __future__ import annotations

from pathlib import Path

from scripts.beta_friction_aggregate import aggregate_reports, parse_trial_report


def test_parse_trial_report_extracts_maintainer_smoke_fields() -> None:
    path = Path("docs/zh/reports/S14-beta-user-trial-20260606-maintainer-smoke.md")
    record = parse_trial_report(path)
    assert record.tester == "maintainer-smoke"
    assert record.is_maintainer is True
    assert record.steps_passed.get("A1–A5 安装 + Studio 预览") is True
    assert record.steps_passed.get("B1–B4 Goal 执行") is True
    assert any("repair" in blocker.lower() for blocker in record.blockers)


def test_aggregate_reports_skips_template() -> None:
    summary = aggregate_reports(Path("docs/zh/reports"))
    sources = [record["source"] for record in summary["records"]]
    assert all("template" not in source for source in sources)
    assert summary["report_count"] >= 1
    assert summary["ok"] is True
