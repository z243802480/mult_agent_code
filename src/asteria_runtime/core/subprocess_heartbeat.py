from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_HEARTBEAT_SECONDS = 30.0


def run_with_heartbeat(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    text: bool = True,
    capture_output: bool = True,
    check: bool = False,
    timeout: float | None = None,
    label: str | None = None,
    progress_root: str | Path | None = None,
    heartbeat_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess while emitting low-noise progress heartbeats to stderr."""

    if not capture_output:
        return subprocess.run(
            list(args),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            text=text,
            capture_output=False,
            check=check,
            timeout=timeout,
        )
    if not text:
        raise ValueError("run_with_heartbeat currently requires text=True")

    interval = _heartbeat_interval(heartbeat_seconds)
    if interval <= 0:
        return subprocess.run(
            list(args),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            text=True,
            capture_output=True,
            check=check,
            timeout=timeout,
        )

    command = list(args)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_queue: queue.Queue[str] = queue.Queue()
    stderr_queue: queue.Queue[str] = queue.Queue()
    stdout_thread = threading.Thread(
        target=_read_stream,
        args=(process.stdout, stdout_queue),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stream,
        args=(process.stderr, stderr_queue),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    started = time.monotonic()
    next_heartbeat = started + interval
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    display_label = label or Path(command[0]).name
    progress_path = Path(progress_root) if progress_root is not None else None

    try:
        while process.poll() is None:
            _drain(stdout_queue, stdout_chunks)
            _drain(stderr_queue, stderr_chunks)
            elapsed = time.monotonic() - started
            if timeout is not None and elapsed >= timeout:
                process.kill()
                process.wait(timeout=5)
                _join_reader(stdout_thread, stderr_thread)
                _drain(stdout_queue, stdout_chunks)
                _drain(stderr_queue, stderr_chunks)
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output="".join(stdout_chunks),
                    stderr="".join(stderr_chunks),
                )
            now = time.monotonic()
            if now >= next_heartbeat:
                print(
                    _heartbeat_line(
                        label=display_label,
                        elapsed_seconds=elapsed,
                        timeout_seconds=timeout,
                        progress_root=progress_path,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                next_heartbeat += interval
            time.sleep(0.25)
    finally:
        if process.poll() is None:
            process.kill()

    returncode = process.wait()
    _join_reader(stdout_thread, stderr_thread)
    _drain(stdout_queue, stdout_chunks)
    _drain(stderr_queue, stderr_chunks)
    completed = subprocess.CompletedProcess(
        command,
        returncode,
        "".join(stdout_chunks),
        "".join(stderr_chunks),
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _heartbeat_interval(override: float | None) -> float:
    if override is not None:
        return float(override)
    raw = os.getenv("ASTERIA_HEARTBEAT_SECONDS", str(DEFAULT_HEARTBEAT_SECONDS))
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_HEARTBEAT_SECONDS


def _read_stream(stream: Any, output: queue.Queue[str]) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.readline()
            if chunk == "":
                break
            output.put(chunk)
    finally:
        stream.close()


def _drain(source: queue.Queue[str], target: list[str]) -> None:
    while True:
        try:
            target.append(source.get_nowait())
        except queue.Empty:
            return


def _join_reader(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(timeout=1)


def _heartbeat_line(
    *,
    label: str,
    elapsed_seconds: float,
    timeout_seconds: float | None,
    progress_root: Path | None,
) -> str:
    parts = [
        "[asteria-heartbeat]",
        f"task={label}",
        f"elapsed={int(elapsed_seconds)}s",
    ]
    if timeout_seconds is not None:
        remaining = max(0, int(timeout_seconds - elapsed_seconds))
        parts.append(f"remaining={remaining}s")
    progress = _workspace_progress(progress_root) if progress_root is not None else None
    if progress:
        parts.extend(progress)
    return " ".join(parts)


def _workspace_progress(root: Path | None) -> list[str]:
    if root is None:
        return []
    asteria_dir = root / ".asteria"
    if not asteria_dir.exists():
        return ["progress=initializing"]
    run_id = _current_run_id(asteria_dir)
    parts: list[str] = []
    run_dir = asteria_dir / "runs" / run_id if run_id else None
    if run_id:
        parts.append(f"run={run_id}")
    if run_dir and run_dir.exists():
        status = _run_status(run_dir)
        if status:
            parts.append(f"status={status}")
        parts.extend(_cost_parts(run_dir))
        last_event = _last_jsonl(run_dir / "events.jsonl")
        if last_event:
            event_type = last_event.get("event_type") or last_event.get("type")
            if event_type:
                parts.append(f"last_event={event_type}")
        last_model = _last_jsonl(run_dir / "model_calls.jsonl")
        if last_model:
            parts.extend(_model_parts(last_model))
    elif run_id:
        parts.append("progress=run-starting")
    else:
        parts.append("progress=awaiting-run")
    return parts


def _current_run_id(asteria_dir: Path) -> str | None:
    session = _read_json(asteria_dir / "current_session.json")
    if isinstance(session, dict):
        run_id = session.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    runs_dir = asteria_dir / "runs"
    if not runs_dir.exists():
        return None
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda path: path.stat().st_mtime).name


def _run_status(run_dir: Path) -> str | None:
    data = _read_json(run_dir / "run.json")
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    return status if isinstance(status, str) else None


def _cost_parts(run_dir: Path) -> list[str]:
    data = _read_json(run_dir / "cost_report.json")
    if not isinstance(data, dict):
        return []
    parts: list[str] = []
    for key, label in (
        ("model_calls", "model_calls"),
        ("tool_calls", "tool_calls"),
        ("repair_attempts", "repairs"),
        ("context_compactions", "compactions"),
    ):
        value = data.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label}={int(value)}")
    return parts


def _model_parts(call: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    tier = call.get("model_tier") or call.get("tier")
    provider = call.get("model_provider") or call.get("provider")
    if isinstance(tier, str) and tier:
        parts.append(f"route={tier}")
    if isinstance(provider, str) and provider:
        parts.append(f"provider={provider}")
    streaming = call.get("streaming")
    if isinstance(streaming, dict):
        mode = streaming.get("mode")
        if isinstance(mode, str) and mode:
            parts.append(f"stream={mode}")
        first_chunk_ms = streaming.get("first_chunk_ms")
        if isinstance(first_chunk_ms, (int, float)):
            parts.append(f"first_chunk_ms={int(first_chunk_ms)}")
    duration_ms = call.get("duration_ms")
    if isinstance(duration_ms, (int, float)):
        parts.append(f"last_call_ms={int(duration_ms)}")
    return parts


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _last_jsonl(path: Path) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None
