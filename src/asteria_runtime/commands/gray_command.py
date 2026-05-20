from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.gray_run_command import GrayRunCommand


@dataclass(frozen=True)
class GrayCommandResult:
    root: Path
    status: str
    gate_status: dict[str, Any] = field(default_factory=dict)
    gray_run: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"dry_run_ready", "blocked"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "status": self.status,
            "ok": self.status == "dry_run_ready",
            "mode": "dry_run",
            "gate_status": self.gate_status,
            "gray_run": self.gray_run,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            "Gray",
            f"Root: {self.root}",
            f"Status: {self.status}",
            "Mode: dry_run",
            f"Gate stage: {self.gate_status.get('stage', 'unknown')}",
        ]
        if self.gray_run:
            lines.append(f"Gray run summary: {self.gray_run.get('summary_path')}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class GrayCommand:
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

    def run(self) -> GrayCommandResult:
        gate_status = GateStatusCommand(self.root).run().to_dict()
        gray_run_result = GrayRunCommand(
            root=self.root,
            goal=self.goal,
            dry_run=True,
            summary_json=self.summary_json,
        ).run()
        gray_run = gray_run_result.to_dict()
        status = "dry_run_ready" if gray_run_result.status == "dry_run" else "blocked"
        return GrayCommandResult(
            root=self.root,
            status=status,
            gate_status=gate_status,
            gray_run=gray_run,
            next_actions=list(gray_run_result.next_actions),
        )
