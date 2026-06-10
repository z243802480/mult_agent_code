from __future__ import annotations

from pathlib import Path

from scripts.beta_friction_aggregate import (
    aggregate_reports,
    aggregate_studio_buckets,
    classify_blocker_bucket,
    parse_trial_report,
)


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
    assert summary["non_maintainer_count"] == 0
    assert summary["completed_abc_count"] == 0
    assert summary["ok"] is True
    studio = summary["studio_friction"]
    assert "buckets" in studio
    assert set(studio["buckets"]) >= {"diff", "context", "session", "side_ask", "other"}
    assert studio["top_bucket"] is None
    assert summary["diagnostics"]["studio_friction"]["top_bucket"] == "session"


def test_classify_blocker_bucket_maps_studio_pain_points() -> None:
    assert classify_blocker_bucket("Diff review 找不到 T2 diff") == "diff"
    assert classify_blocker_bucket("context 压力条看不懂") == "context"
    assert classify_blocker_bucket("切换 session 后 goal 丢了") == "session"
    assert classify_blocker_bucket("Side chat Ctrl+; 没反应") == "side_ask"
    assert classify_blocker_bucket("repair 偏多") == "other"


def test_aggregate_studio_buckets_empty_when_no_beta_reports() -> None:
    studio = aggregate_studio_buckets([])
    assert studio["top_bucket"] is None
    assert studio["next_slice_rule"] == "defer — no Studio friction top bucket yet"


def test_unknown_trial_record_is_diagnostic_not_beta(tmp_path: Path) -> None:
    report = tmp_path / "S14-beta-user-trial-unknown.md"
    report.write_text(
        "# Trial\n\n## 5. 阻塞与反馈\n\n- session switch was confusing\n",
        encoding="utf-8",
    )

    summary = aggregate_reports(tmp_path)

    assert summary["non_maintainer_count"] == 0
    assert summary["diagnostic_record_count"] == 1
    assert summary["studio_friction"]["top_bucket"] is None
    assert summary["diagnostics"]["studio_friction"]["top_bucket"] == "session"
