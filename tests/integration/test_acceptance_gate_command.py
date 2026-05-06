from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agent_runtime.commands.acceptance_gate_command import AcceptanceGateCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_acceptance_gate_passes_clean_report(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [
                scenario("file_smoke", True),
                scenario("password_cli", True),
                scenario("markdown_kb", True),
                scenario("safe_file_renamer", True),
            ],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=4,
    ).run()

    assert result.ok
    assert result.release_status == "ready"
    assert result.passed_count == 4
    assert "Status: pass" in result.to_text()


def test_acceptance_gate_blocks_trend_warnings_by_default(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "trend_warnings": ["model calls increased by 6 (threshold 5)"],
            "scenarios": [scenario("password_cli", True)],
        },
    )

    result = AcceptanceGateCommand(tmp_path, report_path=report_path).run()

    assert not result.ok
    assert result.release_status == "blocked"
    assert "acceptance trend warnings are present" in result.failures
    assert "agent /acceptance-history" in result.next_actions[0]


def test_acceptance_gate_allows_closed_repair_with_conditional_status(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": False,
            "returncode": 1,
            "scenarios": [scenario("markdown_kb", False)],
            "repair_closure": {
                "repair_run_id": "run-1",
                "rerun_summary_json": str(tmp_path / "rerun.json"),
                "rerun_ok": True,
                "closed_failures": ["markdown_kb"],
                "remaining_failures": [],
            },
        },
    )

    result = AcceptanceGateCommand(tmp_path, report_path=report_path).run()

    assert result.ok
    assert result.release_status == "conditional"
    assert "base acceptance failed" in result.warnings[0]


def test_acceptance_gate_cli_exits_nonzero_for_blocked_release(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": False,
            "returncode": 1,
            "scenarios": [scenario("password_cli", False)],
        },
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_runtime",
            "/acceptance-gate",
            "--root",
            str(tmp_path),
            "--report",
            str(report_path),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Release status: blocked" in completed.stdout
    assert "repair closure did not prove recovery" in completed.stdout


def scenario(name: str, ok: bool) -> dict:
    return {
        "scenario": name,
        "ok": ok,
        "workspace": None,
        "failure_summary": "" if ok else f"{name} failed",
        "stdout_tail": "",
        "stderr_tail": "",
        "summary": {},
    }


def write_report(tmp_path: Path, overrides: dict) -> Path:
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": True,
        "returncode": 0,
        "created_at": "2026-05-06T12:00:00+08:00",
        "summary_json": str(tmp_path / ".agent" / "acceptance" / "latest_summary.json"),
        "aggregate": {},
        "trend": {},
        "trend_warnings": [],
        "scenarios": [],
    }
    report.update(overrides)
    report.setdefault("aggregate", {})
    report.setdefault("trend", {})
    report.setdefault("trend_warnings", [])
    report_path = tmp_path / ".agent" / "acceptance" / "acceptance_report.json"
    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        report_path,
        report,
        "acceptance_report",
    )
    return report_path
