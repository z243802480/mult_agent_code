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

import json
import os
from pathlib import Path

PAUSE_SIGNAL_NAME = "pause.request"
STEER_SIGNAL_NAME = "steer.request"


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


# ── Mid-run steer (ADR-0029 ①) ───────────────────────────────────────────────
# Same shape as pause, different intent: instead of stopping the run, hand the model a new user
# instruction at its next turn boundary and let it carry on. The running loop reads-and-clears the
# signal at that boundary and appends the text as the model's next user message (via the exact
# `messages.append(role="user", …)` path the turn_start hook already uses) — so the model, not the
# harness, decides what to do with it (ADR-0016: cognition stays with the model, the harness only
# delivers at a clean boundary). Injected verbatim: never parsed into a next_action, never applied
# mid-tool-batch. A file because the run is a separate process, exactly like pause.


def steer_signal_path(run_dir: Path) -> Path:
    return Path(run_dir) / STEER_SIGNAL_NAME


def request_steer(run_dir: Path, instruction: str) -> Path | None:
    """Queue a user instruction for the run's next turn boundary. Appends, so several steers sent in
    a row all land and drain in order. Empty text is a no-op."""
    text = (instruction or "").strip()
    if not text:
        return None
    path = steer_signal_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"instruction": text}, ensure_ascii=False) + "\n")
    return path


def take_steer(run_dir: Path) -> list[str]:
    """Read-and-clear the pending steer instructions, in the order they were queued.

    Read-and-clear so each instruction is injected exactly once. We rename first, then read the
    renamed copy: a steer appended in the window between read and delete would otherwise be lost —
    with the rename, such a late write lands in a fresh signal file and is simply picked up at the
    NEXT boundary instead. If the rename can't happen (e.g. the writer holds the file open for its
    quick append on Windows), we leave the signal in place and try again next turn — never dropping.
    """
    path = steer_signal_path(run_dir)
    if not path.exists():
        return []
    taking = path.with_name(STEER_SIGNAL_NAME + ".taking")
    try:
        os.replace(path, taking)
    except OSError:
        return []  # writer busy — leave the signal; next boundary retries, nothing lost
    try:
        raw = taking.read_text(encoding="utf-8")
    except OSError:
        raw = ""
    finally:
        try:
            taking.unlink()
        except OSError:
            pass
    instructions: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            text = str(json.loads(line).get("instruction", "")).strip()
        except (ValueError, TypeError):
            text = line  # tolerate a plain-text instruction line
        if text:
            instructions.append(text)
    return instructions
