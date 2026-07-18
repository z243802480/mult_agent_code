"""Cross-process single-writer lock for a workspace root (S88).

S87 put the one-writer-at-a-time guard in Studio's BFF (`studio/lib/run-conflict.mjs`) —
in-memory, so it only sees runs that pass through `startRuntimeJob`. Two CLI terminals, or a
CLI run next to a Studio run, are separate OS processes the BFF never sees; the 1.2.109 probe
proved they really do run concurrently and write source_root with no lock at all (the default
serial path writes through PathGuard(context.root) directly — no candidate workspace, and
_PROMOTION_APPLY_LOCK is process-local).

This module is the cross-process layer: an OS-held, non-blocking file lock on
``root/.asteria/locks/writer.lock``. The OS releases it when the holding process dies, so
there is no stale-lock breaking logic — deliberately, because PID liveness probing is where
this would rot (on Windows, ``os.kill(pid, 0)`` *terminates* the process).

Scope mirrors run-conflict.mjs: read-only commands (chat/ask, plan, review, status,
``promotions list``) never touch this lock — asking a question while a run is in flight must
keep working. Everything that can reach the user's files goes through one of three chokepoints
that acquire it: RunCommand.continue_run, ExecuteCommand.run, PromotionsCommand.run (non-list).
CLI ``decide`` writes only .asteria decision records and stays outside; if it ever grows a
path that writes user files, it must be added here — the inverted default does not cover it.

Same-process nesting (run → execute, repeated ExecuteCommand instances inside one run) is
re-entrant via a process-level registry, so only the outermost holder touches the OS lock.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Mirrors GOAL_ECHO_LIMIT in studio/lib/run-conflict.mjs: past this the echoed goal stops
# identifying a task and starts being a wall.
_GOAL_ECHO_LIMIT = 60


class WorkspaceBusyError(RuntimeError):
    """Another process is already running a writer against this workspace."""


class _Held:
    __slots__ = ("fd", "count")

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.count = 1


_REGISTRY: dict[str, _Held] = {}
_REGISTRY_GUARD = threading.Lock()


def _lock_paths(root: Path) -> tuple[Path, Path]:
    locks_dir = root.resolve() / ".asteria" / "locks"
    return locks_dir / "writer.lock", locks_dir / "writer.holder.json"


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            # Locking one byte past EOF is valid on Windows; nothing is ever written to the
            # lock file itself (its region lock is mandatory — a write would block readers).
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _unlock(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass  # closing the fd releases the OS lock regardless


def _busy_message(holder_path: Path) -> str:
    """The refusal a user reads. Names the holder and says what to do — wording kept in step
    with blockedNotice() in run-conflict.mjs, and it must never imply their files were touched."""
    what = "另一个任务正在这个工作区里跑"
    hint = "等它跑完再发一次，或者先去停掉它"
    try:
        holder = json.loads(holder_path.read_text(encoding="utf-8"))
        goal = str(holder.get("goal") or "").strip()
        if len(goal) > _GOAL_ECHO_LIMIT:
            goal = f"{goal[:_GOAL_ECHO_LIMIT]}…"
        detail_parts = [str(holder.get("command") or "").strip() or "run"]
        pid = holder.get("pid")
        if isinstance(pid, int):
            detail_parts.append(f"PID {pid}")
            hint = f"等它跑完再发一次，或者先去停掉它（结束 PID {pid} 那个进程）"
        started = str(holder.get("started_at") or "").strip()
        if started:
            detail_parts.append(f"{started} 起")
        detail = "·".join(detail_parts)
        what = (
            f"另一个任务正在这个工作区里跑：{goal}（{detail}）"
            if goal
            else f"另一个任务正在这个工作区里跑（{detail}）"
        )
    except (OSError, ValueError):
        pass  # holder metadata is best-effort; the refusal stands without it
    return (
        f"{what}。两个任务同时改同一批文件会互相覆盖，"
        f"所以这次没有开始——你的文件没有被动过。{hint}。"
    )


@contextmanager
def workspace_writer_lock(root: Path, *, command: str, goal: str | None = None) -> Iterator[None]:
    """Hold the workspace's single-writer lock for the duration of the block.

    Non-blocking: if another process holds it, raises WorkspaceBusyError immediately with a
    message that names the holder. Re-entrant within one process (per workspace root).
    """
    lock_path, holder_path = _lock_paths(Path(root))
    key = str(lock_path)
    with _REGISTRY_GUARD:
        held = _REGISTRY.get(key)
        if held is not None:
            held.count += 1
        else:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
            if not _try_lock(fd):
                os.close(fd)
                raise WorkspaceBusyError(_busy_message(holder_path))
            try:
                holder_path.write_text(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "command": command,
                            "goal": (goal or "").strip() or None,
                            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass  # metadata is for the refusal message only; the lock itself is held
            _REGISTRY[key] = _Held(fd)
    try:
        yield
    finally:
        with _REGISTRY_GUARD:
            held = _REGISTRY.get(key)
            if held is not None:
                held.count -= 1
                if held.count <= 0:
                    del _REGISTRY[key]
                    try:
                        holder_path.unlink()
                    except OSError:
                        pass
                    _unlock(held.fd)
                    os.close(held.fd)
