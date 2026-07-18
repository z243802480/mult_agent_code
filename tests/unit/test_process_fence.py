"""ADR-0030 S-A: the process fence must be transparent to normal commands, mirror subprocess.run's
timeout contract, and — the whole point — reap a detached child when the run ends."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from asteria_runtime.core.process_fence import run_fenced


def test_captures_output_and_returncode(tmp_path: Path) -> None:
    result = run_fenced(
        f'"{sys.executable}" -c "print(\'hello fence\')"',
        cwd=tmp_path,
        env=_env(),
        timeout=30,
    )
    assert result.returncode == 0
    assert "hello fence" in result.stdout


def test_nonzero_exit_is_reported_not_raised(tmp_path: Path) -> None:
    result = run_fenced(
        f'"{sys.executable}" -c "import sys; sys.exit(3)"',
        cwd=tmp_path,
        env=_env(),
        timeout=30,
    )
    assert result.returncode == 3


def test_timeout_raises_with_captured_output(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_fenced(
            f'"{sys.executable}" -c "import time; print(\'started\'); time.sleep(30)"',
            cwd=tmp_path,
            env=_env(),
            timeout=1,
        )


@pytest.mark.skipif(sys.platform != "win32", reason="KILL_ON_JOB_CLOSE reaping is the Windows path")
def test_detached_child_is_reaped_when_run_ends(tmp_path: Path) -> None:
    # The command spawns a DETACHED grandchild that appends to a file forever, then the command
    # itself returns immediately. Without the fence the grandchild outlives the run and keeps
    # writing; with KILL_ON_JOB_CLOSE it dies the moment the job handle closes.
    marker = tmp_path / "heartbeat.txt"
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import time\n"
        f"p = r'{marker}'\n"
        "while True:\n"
        "    open(p, 'a').write('x')\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    # DETACHED_PROCESS (0x8) — the grandchild has no ties to the command; only the Job reaches it.
    launcher = (
        f'"{sys.executable}" -c "import subprocess; '
        f"subprocess.Popen([r'{sys.executable}', r'{child_script}'], creationflags=0x00000008)\""
    )
    result = run_fenced(launcher, cwd=tmp_path, env=_env(), timeout=30)
    assert result.returncode == 0

    # Give the grandchild a moment to have been writing, then confirm it has STOPPED (was reaped).
    time.sleep(0.5)
    size_after_run = marker.stat().st_size if marker.exists() else 0
    time.sleep(0.6)
    size_later = marker.stat().st_size if marker.exists() else 0
    assert size_later == size_after_run, (
        f"detached child kept writing after the run ended ({size_after_run} -> {size_later}); "
        "KILL_ON_JOB_CLOSE did not reap it"
    )


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)
