from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.readiness_run_command import ReadinessRunCommand


@dataclass(frozen=True)
class ReadinessCommandResult:
    root: Path
    status: str
    gate_status: dict[str, Any] = field(default_factory=dict)
    readiness_run: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"dry_run_ready", "blocked"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="readiness",
                audience="maintainer_release_readiness",
                stable_fields=[
                    "schema_version",
                    "root",
                    "status",
                    "ok",
                    "mode",
                    "gate_status",
                    "readiness_run",
                    "next_actions",
                ],
            ),
            "root": str(self.root),
            "status": self.status,
            "ok": self.status == "dry_run_ready",
            "mode": "dry_run",
            "gate_status": self.gate_status,
            "readiness_run": self.readiness_run,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            "Readiness",
            f"Root: {self.root}",
            f"Status: {self.status}",
            "Mode: dry_run",
            f"Gate stage: {self.gate_status.get('stage', 'unknown')}",
        ]
        if self.readiness_run:
            lines.append(f"Readiness run summary: {self.readiness_run.get('summary_path')}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class ReadinessCommand:
    def __init__(
        self,
        root: Path,
        goal: str | None = None,
        *,
        summary_json: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.summary_json = summary_json

    def run(self) -> ReadinessCommandResult:
        gate_status = GateStatusCommand(self.root).run().to_dict()
        readiness_run_result = ReadinessRunCommand(
            root=self.root,
            goal=self.goal,
            dry_run=True,
            summary_json=self.summary_json,
        ).run()
        readiness_run = readiness_run_result.to_dict()
        status = "dry_run_ready" if readiness_run_result.status == "dry_run" else "blocked"
        return ReadinessCommandResult(
            root=self.root,
            status=status,
            gate_status=gate_status,
            readiness_run=readiness_run,
            next_actions=list(readiness_run_result.next_actions),
        )
