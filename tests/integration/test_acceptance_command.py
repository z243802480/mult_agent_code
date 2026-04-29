from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_acceptance_command_runs_offline_suite_with_fake_provider(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["AGENT_MODEL_PROVIDER"] = "fake"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_runtime",
            "/acceptance",
            "--suite",
            "offline",
            "--root",
            str(tmp_path / "acceptance"),
            "--summary-json",
            str(summary_path),
            "--allow-fake",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Acceptance" in completed.stdout
    assert "Status: pass" in completed.stdout
    assert "Report:" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["scenarios"][0]["scenario"] == "offline_artifact"
    report_path = tmp_path / "acceptance" / ".agent" / "acceptance" / "acceptance_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["summary_json"] == str(summary_path)
    assert report["scenarios"][0]["scenario"] == "offline_artifact"
