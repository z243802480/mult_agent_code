from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_model_smoke_script_validates_offline_flow_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_smoke.py",
            "--root",
            str(workspace),
            "--allow-fake",
            "--goal",
            "create offline artifact",
            "--expected-file",
            "offline_artifact.txt",
            "--expected-text",
            "offline verification artifact",
            "--summary-json",
            str(summary_path),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Real model smoke passed" in completed.stdout
    assert (workspace / "offline_artifact.txt").exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"].startswith("run-")
    assert Path(summary["final_report"]).exists()
    assert [command["name"] for command in summary["commands"]] == [
        "init",
        "model-check",
        "run",
    ]


def test_real_model_smoke_script_rejects_fake_provider_by_default(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_smoke.py",
            "--root",
            str(tmp_path / "workspace"),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Use --allow-fake only for script tests" in completed.stderr
