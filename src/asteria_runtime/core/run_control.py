"""User-initiated pause: a cooperative stop signal for a run that is already in flight.

Why a signal file and not an OS suspend (SIGSTOP / thread suspend): freezing the process mid-tool
leaves it holding file handles and half-written artifacts, its provider connections time out anyway,
and — the part that actually matters — you cannot *change your instructions* while it is frozen. That
is not a pause, it is a hang.

What users want from pause is what mainstream coding agents give them: stop at a safe boundary, keep
everything that was done, let me say something, carry on from there. So pause here is COOPERATIVE:
the caller drops a signal, the running loop notices it at a turn boundary — after the previous tool
batch has finished, before the next model call — and exits cleanly with status "paused". Nothing is
half-executed, the run is resumable with `asteria resume`, and the user can add guidance first.

The signal is a file because the run is a separate process: Studio (or the CLI) cannot reach into it,
but both can see its run directory.
"""

from __future__ import annotations

from pathlib import Path

PAUSE_SIGNAL_NAME = "pause.request"


def pause_signal_path(run_dir: Path) -> Path:
    return Path(run_dir) / PAUSE_SIGNAL_NAME


def request_pause(run_dir: Path, *, reason: str = "user requested pause") -> Path:
    """Ask the run to stop at its next turn boundary. Idempotent."""
    path = pause_signal_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason, encoding="utf-8")
    return path


def pause_requested(run_dir: Path) -> bool:
    return pause_signal_path(run_dir).exists()


def pause_reason(run_dir: Path) -> str:
    try:
        return pause_signal_path(run_dir).read_text(encoding="utf-8").strip() or "user requested pause"
    except OSError:
        return "user requested pause"


def clear_pause(run_dir: Path) -> None:
    """Consume the signal.

    Called when the loop honours the pause AND when a run resumes. Leaving a stale signal behind
    would make the very next resume pause again on its first turn — a run that can never restart.
    """
    try:
        pause_signal_path(run_dir).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
