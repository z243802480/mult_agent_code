from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from asteria_runtime.core.subprocess_heartbeat import run_with_heartbeat


def test_run_with_heartbeat_preserves_captured_output(tmp_path: Path) -> None:
    completed = run_with_heartbeat(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
        heartbeat_seconds=0,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "ok"
    assert completed.stderr == ""


def test_run_with_heartbeat_raises_timeout_with_output(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        run_with_heartbeat(
            [
                sys.executable,
                "-c",
                "import sys, time; print('before'); sys.stdout.flush(); time.sleep(3)",
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=0.5,
            heartbeat_seconds=0.1,
        )

    assert "before" in str(exc_info.value.output)


def test_run_with_heartbeat_emits_runtime_progress(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = "run-test"
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (tmp_path / ".asteria" / "current_session.json").write_text(
        json.dumps({"run_id": run_id}),
        encoding="utf-8",
    )
    (run_dir / "run.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run_dir / "cost_report.json").write_text(
        json.dumps({"model_calls": 2, "tool_calls": 1}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "task_started"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "model_calls.jsonl").write_text(
        json.dumps(
            {
                "model_tier": "strong",
                "model_provider": "glm",
                "duration_ms": 1200,
                "streaming": {"mode": "streaming", "first_chunk_ms": 300},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = run_with_heartbeat(
        [sys.executable, "-c", "import time; time.sleep(0.35); print('done')"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
        heartbeat_seconds=0.1,
        label="demo",
        progress_root=tmp_path,
    )

    assert completed.returncode == 0
    stderr = capsys.readouterr().err
    assert "[asteria-heartbeat]" in stderr
    assert "task=demo" in stderr
    assert f"run={run_id}" in stderr
    assert "status=running" in stderr
    assert "route=strong" in stderr
    assert "stream=streaming" in stderr
