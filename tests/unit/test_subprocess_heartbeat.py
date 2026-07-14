from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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


def test_run_with_heartbeat_timeout_terminates_child_process(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    parent_code = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"open({str(child_pid_file)!r}, 'w', encoding='utf-8').write(str(child.pid)); "
        "time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        run_with_heartbeat(
            [sys.executable, "-c", parent_code],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=0.5,
            heartbeat_seconds=0,
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _process_exists(child_pid):
        time.sleep(0.1)
    assert not _process_exists(child_pid)


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


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # os.kill(pid, 0) also succeeds for a ZOMBIE — a process that is already dead but whose exit
    # status has not been reaped yet. When we kill the process group, the grandchild dies immediately
    # but lingers as a zombie until init reparents and reaps it, which on a CI runner can take longer
    # than this test's window. Treating that as "still running" failed the test while the kill had in
    # fact worked. "Exists" must mean "still running".
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    # /proc/<pid>/stat: "<pid> (<comm>) <state> ..." — comm can contain spaces/parens, so split at the
    # LAST ')'.
    state = stat.rpartition(")")[2].split()
    return bool(state) and state[0] != "Z"
