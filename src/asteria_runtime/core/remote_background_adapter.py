from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.core.local_background_run import (
    BackgroundRunRegistry,
    background_run_projection,
    start_local_background_run,
)
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso

SpawnProcess = Callable[..., Any]

REMOTE_ADAPTER_ID = "stub"
REMOTE_DEFER_REASON = "Cloud VM orchestration deferred; registry records intent only."


@dataclass(frozen=True)
class RemoteBackgroundStubBandResult:
    ok: bool
    background_run_id: str
    status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "background_run_id": self.background_run_id,
            "status": self.status,
            "summary": self.summary,
        }


def background_backend_capabilities() -> dict[str, Any]:
    return {
        "local_subprocess": True,
        "remote_adapter": REMOTE_ADAPTER_ID,
        "remote_available": False,
        "cloud_vm_deferred": True,
        "implementation_status": "stub_only",
    }


def start_remote_background_stub(
    root: Path,
    goal: str,
    validator: SchemaValidator,
) -> dict[str, Any]:
    root = root.resolve()
    registry = BackgroundRunRegistry(root, validator)
    background_run_id = f"bg-remote-{now_iso().replace(':', '').replace('+', '')[:15]}"
    started_at = now_iso()
    entry: dict[str, Any] = {
        "background_run_id": background_run_id,
        "status": "deferred",
        "goal": goal.strip(),
        "local_subprocess": False,
        "cloud_vm": True,
        "remote_adapter": REMOTE_ADAPTER_ID,
        "deployment_target": None,
        "deferred_reason": REMOTE_DEFER_REASON,
        "started_at": started_at,
        "updated_at": started_at,
        "summary": REMOTE_DEFER_REASON,
    }
    registry.append_run(entry)
    return entry


def start_background_run(
    root: Path,
    goal: str,
    validator: SchemaValidator,
    *,
    remote: bool = False,
    spawn: SpawnProcess | None = None,
) -> dict[str, Any]:
    if remote:
        return start_remote_background_stub(root, goal, validator)
    return start_local_background_run(root, goal, validator, spawn=spawn)


def merge_backend_projection(projection: dict[str, Any]) -> dict[str, Any]:
    payload = dict(projection)
    payload.update(background_backend_capabilities())
    return payload


def run_remote_background_stub_band(
    root: Path,
    validator: SchemaValidator,
) -> RemoteBackgroundStubBandResult:
    from asteria_runtime.commands.init_command import InitCommand

    root.mkdir(parents=True, exist_ok=True)
    InitCommand(root).run()
    entry = start_remote_background_stub(root, "Remote stub band goal", validator)
    projection = merge_backend_projection(background_run_projection(root, validator))
    registry = BackgroundRunRegistry(root, validator)
    data = registry.read()
    runs = [item for item in (data.get("runs") or []) if isinstance(item, dict)]
    latest = runs[-1] if runs else {}
    ok = (
        str(latest.get("background_run_id")) == str(entry["background_run_id"])
        and latest.get("status") == "deferred"
        and latest.get("cloud_vm") is True
        and latest.get("remote_adapter") == REMOTE_ADAPTER_ID
        and projection.get("remote_available") is False
    )
    return RemoteBackgroundStubBandResult(
        ok=ok,
        background_run_id=str(entry["background_run_id"]),
        status=str(entry.get("status") or "deferred"),
        summary="Remote background stub band passed." if ok else "Remote background stub band blocked.",
    )
