from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.local_background_run import (
    BackgroundGoalOptions,
    BackgroundRunRegistry,
    background_run_projection,
)
from asteria_runtime.core.remote_background_adapter import start_background_run
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class BackgroundRunResult:
    action: str
    ok: bool
    summary: str
    background_run_id: str | None = None
    pid: int | None = None
    status: str | None = None
    goal: str | None = None
    registry_path: Path | None = None
    projection: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "action": self.action,
            "ok": self.ok,
            "summary": self.summary,
            "background_run_id": self.background_run_id,
            "pid": self.pid,
            "status": self.status,
            "goal": self.goal,
            "registry_path": str(self.registry_path) if self.registry_path else None,
            "projection": self.projection,
        }

    def to_text(self) -> str:
        lines = [f"Background run ({self.action}): {self.summary}"]
        if self.background_run_id:
            lines.append(f"ID: {self.background_run_id}")
        if self.pid is not None:
            lines.append(f"PID: {self.pid}")
        if self.status:
            lines.append(f"Status: {self.status}")
        if self.registry_path:
            lines.append(f"Registry: {self.registry_path}")
        if self.projection:
            lines.append(
                f"Running: {self.projection.get('running_count', 0)}/"
                f"{self.projection.get('total_count', 0)}"
            )
        return "\n".join(lines)


class BackgroundRunCommand:
    def __init__(
        self,
        root: Path,
        *,
        action: str = "status",
        goal: str | None = None,
        remote: bool = False,
        validator: SchemaValidator | None = None,
        options: BackgroundGoalOptions | None = None,
    ) -> None:
        self.root = root.resolve()
        self.action = action.strip().lower()
        self.goal = goal.strip() if goal else None
        self.remote = remote
        self.validator = validator or SchemaValidator(schema_dir())
        self.options = options

    def run(self) -> BackgroundRunResult:
        if not (self.root / ".asteria").exists():
            InitCommand(self.root).run()

        if self.action == "start":
            if not self.goal:
                raise ValueError("goal is required for `asteria background start`.")
            entry = start_background_run(
                self.root,
                self.goal,
                self.validator,
                remote=self.remote,
                options=self.options,
            )
            registry = BackgroundRunRegistry(self.root, self.validator)
            if self.remote:
                return BackgroundRunResult(
                    action="start",
                    ok=False,
                    summary=str(entry.get("summary") or entry.get("deferred_reason") or "Remote background deferred."),
                    background_run_id=str(entry["background_run_id"]),
                    status=str(entry.get("status") or "deferred"),
                    goal=str(entry.get("goal") or ""),
                    registry_path=registry.path,
                )
            return BackgroundRunResult(
                action="start",
                ok=True,
                summary="Local background subprocess started.",
                background_run_id=str(entry["background_run_id"]),
                pid=int(entry["pid"]) if entry.get("pid") is not None else None,
                status=str(entry.get("status") or "running"),
                goal=str(entry.get("goal") or ""),
                registry_path=registry.path,
            )

        projection = background_run_projection(self.root, self.validator)
        if self.action == "list":
            return BackgroundRunResult(
                action="list",
                ok=True,
                summary=projection["badge_summary"],
                projection=projection,
                registry_path=self.root / ".asteria" / "background_run_registry.json",
            )

        return BackgroundRunResult(
            action="status",
            ok=True,
            summary=str(projection["badge_summary"]),
            projection=projection,
            registry_path=self.root / ".asteria" / "background_run_registry.json",
        )
