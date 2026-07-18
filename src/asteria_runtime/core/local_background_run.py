from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from asteria_runtime.core.process_flags import NEW_PROCESS_GROUP_FLAGS
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


REGISTRY_REL = Path(".asteria") / "background_run_registry.json"
BACKGROUND_LOG_DIR_REL = Path(".asteria") / "background_logs"
BACKGROUND_RUN_EVIDENCE_FILE = "background_run.json"
SpawnProcess = Callable[..., Any]


class PopenLike(Protocol):
    pid: int
    returncode: int | None


@dataclass(frozen=True)
class LocalBackgroundRunBandResult:
    ok: bool
    background_run_id: str
    run_id: str | None
    status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "background_run_id": self.background_run_id,
            "run_id": self.run_id,
            "status": self.status,
            "summary": self.summary,
        }


class BackgroundRunRegistry:
    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(schema_dir())
        self.store = JsonStore(self.validator)

    @property
    def path(self) -> Path:
        return self.root / REGISTRY_REL

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "0.1.0",
                "runs": [],
                "updated_at": now_iso(),
            }
        payload = self.store.read(self.path, "background_run_registry")
        return payload if isinstance(payload, dict) else {"schema_version": "0.1.0", "runs": []}

    def write(self, data: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload.setdefault("schema_version", "0.1.0")
        payload["updated_at"] = now_iso()
        self.store.write(self.path, payload, "background_run_registry")
        return self.path

    def append_run(self, entry: dict[str, Any]) -> dict[str, Any]:
        data = self.read()
        runs = list(data.get("runs") or [])
        runs.append(entry)
        data["runs"] = runs[-32:]
        self.write(data)
        return entry

    def update_run(self, background_run_id: str, **fields: Any) -> dict[str, Any] | None:
        data = self.read()
        for item in data.get("runs") or []:
            if not isinstance(item, dict):
                continue
            if item.get("background_run_id") != background_run_id:
                continue
            item.update(fields)
            item["updated_at"] = now_iso()
            self.write(data)
            return item
        return None

    def refresh_statuses(
        self,
        *,
        pid_alive: Callable[[int], bool] | None = None,
        poll: Callable[[int], int | None] | None = None,
    ) -> dict[str, Any]:
        alive = pid_alive or _pid_is_alive
        poll_exit = poll or _poll_exit_code
        data = self.read()
        changed = False
        for item in data.get("runs") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            pid = item.get("pid")
            if status not in {"starting", "running"}:
                continue
            if not isinstance(pid, int) or pid <= 0:
                continue
            if status == "starting":
                if alive(pid):
                    item["status"] = "running"
                    changed = True
                else:
                    item["status"] = "failed"
                    item["exit_code"] = 1
                    item["completed_at"] = now_iso()
                    item["summary"] = "Local background subprocess failed to start."
                    _attach_log_tail(self.root, item)
                    changed = True
                continue
            if alive(pid):
                linked = _link_recent_run(self.root, item)
                if linked:
                    item["run_id"] = linked
                    _write_run_background_evidence(
                        self.root,
                        linked,
                        item,
                        self.validator,
                    )
                    changed = True
                continue
            exit_code = poll_exit(pid)
            item["exit_code"] = 0 if exit_code is None else exit_code
            item["status"] = "completed" if item["exit_code"] == 0 else "failed"
            item["completed_at"] = now_iso()
            item["summary"] = (
                "Local background run completed."
                if item["exit_code"] == 0
                else f"Local background run failed (exit {item['exit_code']})."
            )
            _attach_log_tail(self.root, item)
            changed = True
        if changed:
            self.write(data)
        return data


def registry_path(root: Path) -> Path:
    return root.resolve() / REGISTRY_REL


@dataclass(frozen=True)
class BackgroundGoalOptions:
    """Run flags the foreground `goal` command accepts that must survive the hop into the
    background subprocess. Before this existed, `--background` rebuilt the child argv from
    scratch and dropped everything except goal/root — so the user's explicit
    `--permission-level auto` silently degraded to the `balanced` default (dogfood friction #2,
    run-20260718). Defaults reproduce the historical background behaviour (research off) so a
    caller that passes no options is byte-for-byte unchanged."""

    permission_level: str | None = None
    enable_research: bool = False
    model_strategy: str | None = None


def build_background_goal_argv(
    root: Path, goal: str, options: BackgroundGoalOptions | None = None
) -> list[str]:
    opts = options or BackgroundGoalOptions()
    argv = [
        sys.executable,
        "-m",
        "asteria_runtime.cli",
        "goal",
        goal,
        "--root",
        str(root.resolve()),
    ]
    # Research stays off for a background run unless the user explicitly enabled it; unattended
    # network research would otherwise stall on a permission decision nobody is there to answer.
    if not opts.enable_research:
        argv.append("--no-research")
    # Thread the user's explicit choices so the child run_config matches what they asked for on the
    # command line (the whole point of the fix — no silent downgrade).
    if opts.permission_level:
        argv += ["--permission-level", opts.permission_level]
    if opts.model_strategy:
        argv += ["--model-strategy", opts.model_strategy]
    return argv


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) is not a probe on Windows: CPython routes non-CTRL "signals"
        # through TerminateProcess, so checking liveness would kill the child — the same
        # trap workspace_writer_lock.py's design deliberately routes around (S88).
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            # A process that exited with literal code 259 would read as alive; nothing
            # we spawn exits with STILL_ACTIVE on purpose.
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, just owned by another user
    except OSError:
        return False
    return True


def _poll_exit_code(pid: int) -> int | None:
    if not _pid_is_alive(pid):
        return 0
    return None


def _link_recent_run(root: Path, entry: dict[str, Any]) -> str | None:
    if entry.get("run_id"):
        return str(entry["run_id"])
    runs_root = root / ".asteria" / "runs"
    if not runs_root.is_dir():
        return None
    started_at = str(entry.get("started_at") or "")
    candidates: list[tuple[float, str]] = []
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        run_json = run_dir / "run.json"
        if not run_json.exists():
            continue
        try:
            payload = JsonStore(SchemaValidator(schema_dir())).read(run_json, "run")
        except Exception:  # noqa: BLE001
            continue
        created = str(payload.get("created_at") or "")
        if started_at and created and created < started_at:
            continue
        candidates.append((run_json.stat().st_mtime, run_dir.name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _write_run_background_evidence(
    root: Path,
    run_id: str,
    entry: dict[str, Any],
    validator: SchemaValidator,
) -> Path:
    run_dir = root / ".asteria" / "runs" / run_id
    payload = {
        "schema_version": "0.1.0",
        "background_run_id": entry.get("background_run_id"),
        "status": entry.get("status"),
        "goal": entry.get("goal"),
        "local_subprocess": True,
        "cloud_vm": False,
        "pid": entry.get("pid"),
        "recorded_at": now_iso(),
    }
    path = run_dir / BACKGROUND_RUN_EVIDENCE_FILE
    # No schema contract for the background-run evidence object; explicit opt-out.
    JsonStore(validator).write(path, payload, allow_unvalidated=True)
    return path


def background_run_projection(
    root: Path, validator: SchemaValidator | None = None
) -> dict[str, Any]:
    registry = BackgroundRunRegistry(root, validator)
    data = registry.refresh_statuses()
    runs = [item for item in (data.get("runs") or []) if isinstance(item, dict)]
    running = [item for item in runs if item.get("status") in {"starting", "running"}]
    latest = runs[-1] if runs else None
    projection = {
        "enabled": True,
        "local_subprocess": True,
        "cloud_vm": False,
        "running_count": len(running),
        "total_count": len(runs),
        "badge_status": "running"
        if running
        else ("idle" if not runs else str(latest.get("status") or "idle")),
        "badge_summary": (
            f"{len(running)} local background run(s) active."
            if running
            else "No local background runs active."
        ),
        "latest": latest,
        "running": running[:5],
        "registry_path": str(registry.path.relative_to(root.resolve())).replace("\\", "/"),
    }
    from asteria_runtime.core.remote_background_adapter import merge_backend_projection

    return merge_backend_projection(projection)


def _background_log_path(root: Path, background_run_id: str) -> Path:
    return root.resolve() / BACKGROUND_LOG_DIR_REL / f"{background_run_id}.log"


def _read_log_tail(log_path: Path, max_lines: int = 12) -> str:
    if not log_path.is_file():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _attach_log_tail(root: Path, item: dict[str, Any]) -> None:
    rel = item.get("log_path")
    if not isinstance(rel, str) or not rel.strip():
        return
    tail = _read_log_tail(root / rel)
    if not tail:
        return
    item["log_tail"] = tail
    base = str(item.get("summary") or "").rstrip()
    item["summary"] = f"{base}\n--- log tail ---\n{tail}"


def start_local_background_run(
    root: Path,
    goal: str,
    validator: SchemaValidator,
    *,
    spawn: SpawnProcess | None = None,
    options: BackgroundGoalOptions | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    registry = BackgroundRunRegistry(root, validator)
    background_run_id = f"bg-{now_iso().replace(':', '').replace('+', '')[:15]}"
    command = build_background_goal_argv(root, goal, options)
    started_at = now_iso()
    log_path = _background_log_path(root, background_run_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "background_run_id": background_run_id,
        "status": "starting",
        "goal": goal.strip(),
        "pid": None,
        "local_subprocess": True,
        "cloud_vm": False,
        "command": command,
        "log_path": str(log_path.relative_to(root)).replace("\\", "/"),
        "started_at": started_at,
        "updated_at": started_at,
        "summary": "Local background subprocess started.",
    }
    spawner = spawn or subprocess.Popen
    log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    try:
        process = spawner(
            command,
            cwd=str(root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=NEW_PROCESS_GROUP_FLAGS,
        )
    except OSError as exc:
        log_handle.write(f"spawn failed: {exc}\n")
        log_handle.close()
        entry["status"] = "failed"
        entry["exit_code"] = 1
        entry["summary"] = f"Local background subprocess failed to start: {exc}"
        registry.append_run(entry)
        return entry
    entry["pid"] = int(process.pid)
    registry.append_run(entry)
    log_handle.close()
    return entry


def run_local_background_run_band(
    root: Path,
    validator: SchemaValidator,
) -> LocalBackgroundRunBandResult:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.supervised_goal_loop import prepare_accept_ready_run

    root.mkdir(parents=True, exist_ok=True)
    InitCommand(root).run()
    goal = "Background band goal"

    class _FakeProcess:
        pid = 424242
        returncode: int | None = None

    def fake_spawn(command: list[str], **kwargs: Any) -> _FakeProcess:
        return _FakeProcess()

    entry = start_local_background_run(root, goal, validator, spawn=fake_spawn)
    run_id = prepare_accept_ready_run(root, validator, goal)
    registry = BackgroundRunRegistry(root, validator)
    updated = registry.update_run(
        str(entry["background_run_id"]),
        run_id=run_id,
        status="running",
    )
    if updated:
        _write_run_background_evidence(root, run_id, updated, validator)
    registry.update_run(
        str(entry["background_run_id"]),
        status="completed",
        exit_code=0,
        summary="Local background run completed.",
    )
    projection = background_run_projection(root, validator)
    evidence_ok = (root / ".asteria" / "runs" / run_id / BACKGROUND_RUN_EVIDENCE_FILE).exists()
    ok = evidence_ok and projection["local_subprocess"] is True and projection["cloud_vm"] is False
    return LocalBackgroundRunBandResult(
        ok=ok,
        background_run_id=str(entry["background_run_id"]),
        run_id=run_id,
        status="completed",
        summary="Local background run band passed." if ok else "Local background run band blocked.",
    )
