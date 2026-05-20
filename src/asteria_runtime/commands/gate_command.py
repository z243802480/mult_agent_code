from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.version_command import VersionCommand


@dataclass(frozen=True)
class GateCommandResult:
    root: Path
    status: str
    stages: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "conditional"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "status": self.status,
            "ok": self.ok,
            "mode": "read_only",
            "stages": self.stages,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            "Gate",
            f"Root: {self.root}",
            f"Status: {self.status}",
            "Mode: read_only",
        ]
        package = self.stages.get("package_check", {})
        doctor = self.stages.get("doctor", {})
        gate_status = self.stages.get("gate_status", {})
        lines.append(f"Package check: {package.get('status', 'unknown')}")
        lines.append("Doctor: ok" if doctor.get("ok") else "Doctor: blocked")
        lines.append(f"Gate status: {gate_status.get('stage', 'unknown')}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class GateCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> GateCommandResult:
        version = VersionCommand().run().to_dict()
        package = PackageCheckCommand(self.root).run().to_dict()
        doctor = DoctorCommand(self.root).run().to_dict()
        gate_status = GateStatusCommand(self.root).run().to_dict()
        status = self._status(package, doctor, gate_status)
        actions = self._next_actions(package, doctor, gate_status)
        return GateCommandResult(
            root=self.root,
            status=status,
            stages={
                "version": version,
                "package_check": package,
                "doctor": doctor,
                "gate_status": gate_status,
            },
            next_actions=actions,
        )

    def _status(
        self,
        package: dict[str, Any],
        doctor: dict[str, Any],
        gate_status: dict[str, Any],
    ) -> str:
        if package.get("ok") is not True or doctor.get("ok") is not True:
            return "blocked"
        rollout = gate_status.get("rollout_state")
        if rollout == "release_ready":
            return "ready"
        if rollout == "conditional":
            return "conditional"
        return "blocked"

    def _next_actions(
        self,
        package: dict[str, Any],
        doctor: dict[str, Any],
        gate_status: dict[str, Any],
    ) -> list[str]:
        actions: list[str] = []
        if package.get("ok") is not True:
            actions.extend(str(item) for item in package.get("next_actions", []))
        if doctor.get("ok") is not True:
            actions.extend(str(item) for item in doctor.get("next_actions", []))
        actions.extend(str(item) for item in gate_status.get("next_actions", []))
        return actions
