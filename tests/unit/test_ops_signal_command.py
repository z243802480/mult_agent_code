from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.ops_signal_command import OpsSignalCommand
from asteria_runtime.commands.roadmap_command import RoadmapCommand
from asteria_runtime.commands.weekly_report_command import WeeklyReportCommand
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_ops_signal_records_redacted_usage_signal(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = OpsSignalCommand(
        tmp_path,
        run_id="run-1",
        task_kind="code_change",
        expected_outcome_category="verified_patch",
        artifact_outcome="blocked",
        blocker_category="validation_untrusted",
        trust_risk="report_mismatch",
        summary="Maintainer observed a validation trust issue.",
        evidence_refs=[".asteria/evidence_bundles/evidence-test.zip"],
    ).run()

    assert result.signal is not None
    assert result.signal["signal_id"] == "usage-signal-0001"
    assert result.signal["redacted"] is True
    assert result.summary["status"] == "needs_attention"
    assert result.summary["unresolved"] == 1
    rows = JsonlStore(SchemaValidator(Path.cwd() / "schemas")).read_all(
        tmp_path / ".asteria" / "ops" / "usage_signals.jsonl",
        "usage_signal",
    )
    assert rows[0]["artifact_outcome"] == "blocked"
    assert rows[0]["blocker_category"] == "validation_untrusted"


def test_ops_signal_summary_only_does_not_write(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = OpsSignalCommand(tmp_path, summarize_only=True).run()

    assert result.signal is None
    assert result.summary["status"] == "missing"
    assert not (tmp_path / ".asteria" / "ops" / "usage_signals.jsonl").exists()


def test_ops_signal_cli_outputs_json(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "asteria_runtime",
            "ops-signal",
            "--root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--artifact-outcome",
            "accepted",
            "--note",
            "accepted by maintainer",
            "--analyze",
            "--json",
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["signal"]["artifact_outcome"] == "accepted"
    assert payload["summary"]["status"] == "healthy"
    assert payload["analysis"]["status"] == "collecting"
    assert payload["analysis"]["dogfooding_gate"]["status"] == "collecting"


def test_ops_signal_analysis_outputs_priority_items_and_candidate_decisions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-1",
        artifact_outcome="blocked",
        blocker_category="validation_untrusted",
        trust_risk="report_mismatch",
        summary="blocked by unclear validation evidence",
        evidence_refs=["bundle.zip"],
    ).run()

    result = OpsSignalCommand(tmp_path, summarize_only=True, analyze=True).run()

    assert result.analysis is not None
    assert result.analysis["status"] == "needs_attention"
    assert result.analysis["priority_items"][0]["id"] == "usage-unresolved-artifacts"
    assert result.analysis["roadmap_tasks"][0]["priority"] == "P0"
    decision = result.analysis["candidate_decision_points"][0]
    SchemaValidator(Path.cwd() / "schemas").validate("decision_point", decision)
    assert (tmp_path / ".asteria" / "ops" / "usage_signal_analysis.json").exists()


def test_ops_signal_analysis_supersedes_old_blockers_after_acceptance(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-blocked",
        artifact_outcome="blocked",
        blocker_category="route_guidance_blocked",
        trust_risk="strong_goal_spec_unstable",
        summary="alpha proof blocked by stale route guidance",
        evidence_refs=["old-validation-summary.json"],
    ).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-accepted",
        artifact_outcome="accepted",
        blocker_category="none",
        trust_risk="none",
        summary="alpha proof accepted after fresh validation evidence",
        evidence_refs=["new-validation-summary.json"],
    ).run()

    result = OpsSignalCommand(tmp_path, summarize_only=True, analyze=True).run()

    assert result.summary["status"] == "needs_attention"
    assert result.analysis is not None
    assert result.analysis["status"] == "collecting"
    assert result.analysis["active_summary"]["status"] == "healthy"
    assert result.analysis["active_summary"]["unresolved"] == 0
    assert result.analysis["dogfooding_gate"]["status"] == "collecting"
    assert result.analysis["priority_items"] == []
    assert result.analysis["roadmap_tasks"] == []
    assert result.analysis["superseded_signals"][0]["signal_id"] == "usage-signal-0001"
    assert result.analysis["superseded_signals"][0]["superseded_by_signal_id"] == "usage-signal-0002"


def test_ops_signal_dogfooding_gate_blocks_unresolved_active_signals(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-1",
        artifact_outcome="accepted",
        summary="first scoped dogfooding task accepted",
    ).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-2",
        artifact_outcome="blocked",
        blocker_category="validation_untrusted",
        trust_risk="report_mismatch",
        summary="second scoped dogfooding task blocked",
    ).run()

    result = OpsSignalCommand(tmp_path, summarize_only=True, analyze=True).run()

    assert result.analysis is not None
    assert result.analysis["status"] == "needs_attention"
    assert result.analysis["dogfooding_gate"]["status"] == "blocked"
    assert result.analysis["dogfooding_gate"]["ready_for_next_batch"] is False
    assert result.analysis["priority_items"][0]["id"] == "usage-unresolved-artifacts"


def test_ops_signal_dogfooding_gate_ready_after_three_clean_signals(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    for index in range(1, 4):
        OpsSignalCommand(
            tmp_path,
            run_id=f"run-{index}",
            artifact_outcome="accepted",
            blocker_category="none",
            trust_risk="none",
            summary=f"scoped dogfooding task {index} accepted",
            evidence_refs=[f"evidence-{index}.zip"],
        ).run()

    result = OpsSignalCommand(tmp_path, summarize_only=True, analyze=True).run()

    assert result.analysis is not None
    assert result.analysis["status"] == "healthy"
    assert result.analysis["dogfooding_gate"]["status"] == "ready"
    assert result.analysis["dogfooding_gate"]["sample_count"] == 3
    assert result.analysis["dogfooding_gate"]["ready_for_next_batch"] is True
    assert result.analysis["priority_items"] == []


def test_weekly_and_roadmap_consume_dogfooding_gate(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-1",
        artifact_outcome="accepted",
        blocker_category="none",
        trust_risk="none",
        summary="first scoped dogfooding task accepted",
    ).run()

    weekly = WeeklyReportCommand(tmp_path, week_id="2026-W23").run()
    roadmap = RoadmapCommand(tmp_path).run()

    report = json.loads(weekly.report_path.read_text(encoding="utf-8"))
    assert report["usage_signal_analysis"]["dogfooding_gate"]["status"] == "collecting"
    assert "Collect 2 more clean scoped dogfooding signal(s)." in report["next_actions"]
    roadmap_payload = json.loads(roadmap.roadmap_path.read_text(encoding="utf-8"))
    m5 = next(item for item in roadmap_payload["milestones"] if item["id"] == "M5")
    assert m5["status"] == "in_progress"
    assert "Collect 2 more clean scoped dogfooding signal(s)." in roadmap_payload["next_actions"]
    assert roadmap_payload["next_actions"].count("Collect 2 more clean scoped dogfooding signal(s).") == 1
