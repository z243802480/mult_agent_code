from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_model_acceptance_runs_offline_suite_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env.pop("AGENT_MODEL_PROVIDER", None)
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
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

    assert "Real model acceptance passed" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert [scenario["scenario"] for scenario in summary["scenarios"]] == ["offline_artifact"]
    assert summary["scenarios"][0]["summary"]["run_id"].startswith("run-")


def test_real_model_acceptance_rejects_fake_for_real_scenarios(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
            "--scenario",
            "file_smoke",
            "--root",
            str(tmp_path / "acceptance"),
            "--allow-fake",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Fake/offline acceptance only supports offline_artifact" in completed.stderr


def test_real_model_acceptance_runs_decision_point_without_model(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
            "--scenario",
            "decision_point",
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

    assert "Real model acceptance passed" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scenario = summary["scenarios"][0]
    assert scenario["scenario"] == "decision_point"
    assert scenario["ok"] is True
    assert scenario["summary"]["resolved_decision_id"] == "decision-0001"
    assert scenario["summary"]["resolved_status"] == "resolved"
    assert scenario["summary"]["selected_option_id"] == "cli"
