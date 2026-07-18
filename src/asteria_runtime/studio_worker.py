"""Warm worker for the Studio BFF (ADR-0029 mechanism ②, ring-external).

Why this exists
---------------
Every Studio run is otherwise a fresh ``python -m asteria_runtime run`` cold start:
``cli.py`` pulls ~50 command modules out of 235 runtime files and rebuilds model
clients before the first model call, so ``subprocess cold-start still dominates``
first-token latency (see ``studio/server.mjs``). This module is a long-lived
process that pays the import cost **once** and then serves many runs over
stdin/stdout, so the second run onward starts warm.

What it deliberately does NOT touch
-----------------------------------
The agent turn loop (``core/model_driven_turn.py``) and the execution ring are
untouched — this is purely the *process* boundary. It reuses the exact same
``RunCommand`` entrypoint the CLI uses, so a warm run and a cold run execute
identical code and write identical ``.asteria`` evidence. The only difference is
who paid for the imports.

Protocol (newline-delimited JSON over stdin/stdout)
---------------------------------------------------
The worker is **serial**: it handles one request at a time. That is what makes
the per-request ``os.environ`` override for the Studio event sink safe (a
concurrent worker would race on process-global env — out of scope for v1, see
ADR-0029 option B/pool as the deferred follow-up).

Control messages are emitted to stdout as single lines prefixed with
``CONTROL_PREFIX`` so the BFF can tell them apart from a run's incidental stdout:

    @@ASTERIA_WORKER@@ {"event": "ready"}                         # imports warm
    @@ASTERIA_WORKER@@ {"id": "...", "event": "done",
                        "run_id": "run-...", "status": "completed", "exit_code": 0}
    @@ASTERIA_WORKER@@ {"id": "...", "event": "error",
                        "error": "...", "exit_code": 1}

A request is a JSON object on one stdin line::

    {"id": "req-1", "mode": "run", "root": "/abs/workspace", "goal": "...",
     "max_iterations": 8, "max_tasks_per_iteration": 1, "no_research": true,
     "permission_level": "balanced", "model_strategy": "auto",
     "event_sink": "/abs/events.jsonl", "session_id": "sess-...", "phase": "execute"}

Only ``run``/``goal`` mode is served in v1 (the immediacy-critical path); the BFF
falls back to a cold spawn for other modes.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

CONTROL_PREFIX = "@@ASTERIA_WORKER@@ "

# Modes this warm worker knows how to serve. Anything else → the BFF cold-spawns.
_SERVED_MODES = {"run", "goal"}


def _emit(message: dict[str, Any]) -> None:
    """Write one control line to stdout and flush so the BFF sees it immediately."""
    sys.stdout.write(CONTROL_PREFIX + json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _apply_studio_env(request: dict[str, Any]) -> None:
    """Point the Studio event sink at THIS request's session.

    ``StudioModelEventSink`` reads these three env vars fresh on every model call
    (``models/http_transport.py`` / ``models/fake.py`` build a new sink per call),
    so overriding them here — before ``RunCommand.run()`` — routes every event of
    this run to the right session file. Safe only because the worker is serial.
    """
    for env_key, req_key in (
        ("ASTERIA_STUDIO_EVENT_SINK", "event_sink"),
        ("ASTERIA_STUDIO_SESSION_ID", "session_id"),
        ("ASTERIA_STUDIO_PHASE", "phase"),
    ):
        value = request.get(req_key)
        if value:
            os.environ[env_key] = str(value)
        else:
            os.environ.pop(env_key, None)


def _handle_run(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one run through the same RunCommand the CLI uses. Returns a done message."""
    # Imported lazily so the heavy graph is loaded once, on the first request, and the
    # `ready` handshake (which reports the process is up) is not blocked by it.
    from asteria_runtime.commands.run_command import RunCommand

    goal = request.get("goal")
    if not goal:
        raise ValueError("goal is required for a run request")

    # NB: session_id (for the event sink) is NOT the run_id. The cold path passes no --session-id for
    # run mode, so the runtime auto-generates a run-YYYYMMDD-NNNN id; match that by leaving run_id None
    # unless the BFF explicitly supplies one.
    run_id = request.get("run_id")
    max_iterations = request.get("max_iterations")
    result = RunCommand(
        root=Path(str(request["root"])),
        goal=str(goal),
        run_id=str(run_id) if run_id else None,
        max_iterations=int(max_iterations) if max_iterations is not None else None,
        max_tasks_per_iteration=int(request.get("max_tasks_per_iteration", 1)),
        enable_research=not bool(request.get("no_research", False)),
        parallel_writes=bool(request.get("parallel_writes", False)),
        mode="goal",
        permission_level=str(request.get("permission_level", "balanced")),
        model_strategy=str(request.get("model_strategy", "auto")),
        model_name_overrides=request.get("model_name_overrides") or {},
        continue_session=bool(request.get("continue_session", False)),
    ).run()

    return {
        "id": request.get("id"),
        "event": "done",
        "run_id": result.run_id,
        "status": result.status,
        "exit_code": 0,
    }


def serve(stream: Any = None) -> None:
    """Read request lines until EOF, serving each serially. Blocks; returns on EOF."""
    source = stream if stream is not None else sys.stdin
    _emit({"event": "ready"})
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        request: dict[str, Any]
        try:
            request = json.loads(line)
        except (ValueError, TypeError):
            _emit({"event": "error", "error": "malformed request line", "exit_code": 1})
            continue

        request_id = request.get("id")
        mode = str(request.get("mode", "run"))
        if mode not in _SERVED_MODES:
            _emit(
                {
                    "id": request_id,
                    "event": "error",
                    "error": f"mode {mode!r} not served by warm worker",
                    "exit_code": 1,
                }
            )
            continue

        try:
            _apply_studio_env(request)
            _emit(_handle_run(request))
        except Exception as exc:  # noqa: BLE001 — one bad run must not kill the worker loop
            # A run-level failure is reported and the loop continues; only a hard crash
            # (or the BFF tree-killing us on Stop) ends the process. Mirror the cold path,
            # which also survives one failing run by exiting non-zero for that run only.
            _emit(
                {
                    "id": request_id,
                    "event": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-4000:],
                    "exit_code": 1,
                }
            )


def _prewarm() -> None:
    """Pay the heavy import cost ONCE, at boot, before announcing ``ready``.

    The point of the worker is that no user-visible run waits on the ~50-module
    import graph. If we imported lazily on the first request, that first run would
    still be cold. Importing here — while the BFF is starting us in the background —
    means ``ready`` truthfully signals "warm", and every run the user triggers is
    warm, including the first.
    """
    from asteria_runtime.commands.run_command import RunCommand  # noqa: F401


def main() -> None:
    # Line-buffered stdout so control lines are delivered promptly even without explicit flush.
    # ``reconfigure`` lives on TextIOWrapper, not the ``TextIO`` protocol mypy sees for
    # ``sys.stdout``; narrow with isinstance so the call is type-safe instead of ignored.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    try:
        _prewarm()
    except Exception:  # noqa: BLE001 — if warm-up import fails, still serve; runs will surface the error
        pass
    serve()


if __name__ == "__main__":
    main()
