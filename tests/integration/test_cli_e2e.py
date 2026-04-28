from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run_agent(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-m", "agent_runtime", *args],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_cli_e2e_offline_session_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    init = run_agent(tmp_path, "/init", "--root", str(workspace))
    check = run_agent(tmp_path, "/model-check", "--root", str(workspace))
    new = run_agent(tmp_path, "/new", "create offline artifact", "--root", str(workspace))
    brainstorm = run_agent(tmp_path, "/brainstorm", "--root", str(workspace))
    sessions = run_agent(tmp_path, "/sessions", "--root", str(workspace))
    run = run_agent(tmp_path, "/run", "--root", str(workspace))
    handoff = run_agent(tmp_path, "/handoff", "--root", str(workspace), "--to", "ReviewerAgent")

    assert "Initialized agent workspace" in init.stdout
    assert "Call: ok" in check.stdout
    assert "Created new isolated session" in new.stdout
    assert "Brainstorm run:" in brainstorm.stdout
    assert "Current session:" in sessions.stdout
    assert "Status: completed" in run.stdout
    assert "Created handoff package" in handoff.stdout
    assert (workspace / "offline_artifact.txt").exists()
