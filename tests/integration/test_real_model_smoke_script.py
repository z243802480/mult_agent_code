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
    assert summary["duration_seconds"] >= 0
    assert summary["diagnostics"]["run_status"] == "completed"
    assert summary["diagnostics"]["review_status"] == "pass"
    assert summary["diagnostics"]["model_calls"] > 0
    assert summary["diagnostics"]["tool_calls"] > 0
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


def test_real_model_gate_runs_offline_when_explicitly_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "gate-workspace"
    summary_path = tmp_path / "gate-summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["AGENT_MODEL_STRONG_PROVIDER"] = "fake"
    env["AGENT_MODEL_MEDIUM_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_gate.py",
            "--root",
            str(workspace),
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

    assert "Real model gate passed" in completed.stdout
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["checks"]["strong_model_check"] is True
    assert report["checks"]["medium_model_check"] is True
    assert report["checks"]["smoke"] is True
    assert report["checks"]["strong_route_used"] is True
    assert report["checks"]["medium_route_used"] is True
    assert report["model_call_summary"]["total_model_calls"] > 0
    assert report["routes"]["strong"]["provider"] == "fake"
    assert report["routes"]["medium"]["provider"] == "fake"


def test_real_model_gate_requires_strong_and_medium_routes(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("AGENT_MODEL_STRONG_PROVIDER", None)
    env.pop("AGENT_MODEL_MEDIUM_PROVIDER", None)
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_gate.py",
            "--root",
            str(tmp_path / "gate-workspace"),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "AGENT_MODEL_STRONG_PROVIDER is required" in completed.stderr
