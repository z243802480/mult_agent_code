"""S88: cross-process single-writer lock — same-process re-entrancy, real-subprocess
mutual exclusion, and the refusal message a blocked user reads."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from asteria_runtime.core.workspace_writer_lock import (
    WorkspaceBusyError,
    _busy_message,
    workspace_writer_lock,
)

_HOLD_SCRIPT = """
import sys, time
from pathlib import Path
from asteria_runtime.core.workspace_writer_lock import workspace_writer_lock
root = Path(sys.argv[1])
with workspace_writer_lock(root, command="run", goal="占用者的目标"):
    (root / "child_ready.txt").write_text("ok", encoding="utf-8")
    time.sleep(60)
"""


def test_reentrant_within_one_process(tmp_path: Path) -> None:
    with workspace_writer_lock(tmp_path, command="run", goal="外层"):
        with workspace_writer_lock(tmp_path, command="execute"):
            pass
        # inner exit must not have dropped the outer hold: still re-acquirable in-process
        with workspace_writer_lock(tmp_path, command="execute"):
            pass
    # fully released: a fresh acquire works
    with workspace_writer_lock(tmp_path, command="run"):
        pass


def test_released_when_body_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with workspace_writer_lock(tmp_path, command="run"):
            raise RuntimeError("boom")
    with workspace_writer_lock(tmp_path, command="run"):
        pass


def test_second_process_is_refused_and_told_who_holds_it(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLD_SCRIPT, str(tmp_path)],
        env=env,
    )
    try:
        ready = tmp_path / "child_ready.txt"
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert child.poll() is None, "holder subprocess died before acquiring"
            assert time.monotonic() < deadline, "holder subprocess never acquired the lock"
            time.sleep(0.1)

        with pytest.raises(WorkspaceBusyError) as excinfo:
            with workspace_writer_lock(tmp_path, command="run", goal="第二个终端"):
                pass
        message = str(excinfo.value)
        assert "另一个任务正在这个工作区里跑" in message
        assert "占用者的目标" in message
        assert f"PID {child.pid}" in message
        assert "你的文件没有被动过" in message

        # holder metadata is best-effort: corrupting it degrades the message, not the guard
        holder_path = tmp_path / ".asteria" / "locks" / "writer.holder.json"
        holder_path.write_text("not json{", encoding="utf-8")
        with pytest.raises(WorkspaceBusyError) as excinfo:
            with workspace_writer_lock(tmp_path, command="run"):
                pass
        assert "另一个任务正在这个工作区里跑" in str(excinfo.value)
    finally:
        child.terminate()
        child.wait(timeout=20)

    # the OS releases a dead holder's lock: no stale-lock breaking logic needed or wanted
    deadline = time.monotonic() + 10
    while True:
        try:
            with workspace_writer_lock(tmp_path, command="run"):
                pass
            break
        except WorkspaceBusyError:
            assert time.monotonic() < deadline, "lock not released after holder death"
            time.sleep(0.1)


def test_busy_message_truncates_long_goal(tmp_path: Path) -> None:
    holder_path = tmp_path / "writer.holder.json"
    holder_path.write_text(
        json.dumps(
            {
                "pid": 4242,
                "command": "run",
                "goal": "长" * 80,
                "started_at": "2026-07-18T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    message = _busy_message(holder_path)
    assert "长" * 60 + "…" in message
    assert "长" * 61 not in message
    assert "PID 4242" in message


def test_busy_message_without_holder_file(tmp_path: Path) -> None:
    message = _busy_message(tmp_path / "missing.json")
    assert "另一个任务正在这个工作区里跑" in message
    assert "你的文件没有被动过" in message


def test_lock_file_lives_under_asteria(tmp_path: Path) -> None:
    with workspace_writer_lock(tmp_path, command="run"):
        assert (tmp_path / ".asteria" / "locks" / "writer.lock").exists()
        holder = json.loads(
            (tmp_path / ".asteria" / "locks" / "writer.holder.json").read_text(encoding="utf-8")
        )
        assert holder["pid"] == os.getpid()
    # holder metadata is cleaned up on release; the lock file itself may remain
    assert not (tmp_path / ".asteria" / "locks" / "writer.holder.json").exists()


def test_writer_process_alive_reports_no_holder_for_a_dead_run(tmp_path: Path) -> None:
    # The probe is what tells a stale "status: running" record from a live run. Nothing holds the
    # lock here, so the answer must be "gone" — even though the lock file itself exists.
    from asteria_runtime.core.workspace_writer_lock import (
        workspace_writer_lock,
        writer_process_alive,
    )

    assert writer_process_alive(tmp_path) is False  # no lock file yet

    with workspace_writer_lock(tmp_path, command="execute", goal="x"):
        assert writer_process_alive(tmp_path) is True

    # Lock released (and the file is left behind) — the holder is gone and the probe must say so.
    assert writer_process_alive(tmp_path) is False


def test_writer_process_alive_probe_does_not_keep_others_out(tmp_path: Path) -> None:
    from asteria_runtime.core.workspace_writer_lock import (
        workspace_writer_lock,
        writer_process_alive,
    )

    with workspace_writer_lock(tmp_path, command="execute", goal="x"):
        pass
    writer_process_alive(tmp_path)
    # A probe that forgot to release would make this raise WorkspaceBusyError.
    with workspace_writer_lock(tmp_path, command="execute", goal="y"):
        pass
