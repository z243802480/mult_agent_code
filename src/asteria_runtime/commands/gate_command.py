from __future__ import annotations

import subprocess
import sys
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
    mode: str = "read_only"
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
            "mode": self.mode,
            "stages": self.stages,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            "Gate",
            f"Root: {self.root}",
            f"Status: {self.status}",
            f"Mode: {self.mode}",
        ]
        if self.mode == "release":
            for stage in self.stages.get("release", []):
                label = "[pass]" if stage.get("ok") else "[fail]"
                lines.append(f"{label} {stage.get('name')}: {stage.get('summary')}")
        else:
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
    def __init__(
        self,
        root: Path,
        *,
        stage: str = "read_only",
        report_path: Path | None = None,
        suite: str = "core",
        skip_lint: bool = False,
        skip_typecheck: bool = False,
        skip_tests: bool = False,
        skip_acceptance_gate: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.stage = stage
        self.report_path = report_path
        self.suite = suite
        self.skip_lint = skip_lint
        self.skip_typecheck = skip_typecheck
        self.skip_tests = skip_tests
        self.skip_acceptance_gate = skip_acceptance_gate

    def run(self) -> GateCommandResult:
        if self.stage == "release":
            return self._run_release_gate()
        version = VersionCommand().run().to_dict()
        package = PackageCheckCommand(self.root).run().to_dict()
        doctor = DoctorCommand(self.root).run().to_dict()
        gate_status = GateStatusCommand(self.root).run().to_dict()
        status = self._status(package, doctor, gate_status)
        actions = self._next_actions(package, doctor, gate_status)
        return GateCommandResult(
            root=self.root,
            status=status,
            mode="read_only",
            stages={
                "version": version,
                "package_check": package,
                "doctor": doctor,
                "gate_status": gate_status,
            },
            next_actions=actions,
        )

    def _run_release_gate(self) -> GateCommandResult:
        stages: list[dict[str, Any]] = []
        project_root = self._find_project_root()
        if not self.skip_lint:
            stages.append(self._stage("lint (ruff)", ["ruff", "check", "."], project_root))
        if not self.skip_typecheck:
            stages.append(self._stage("typecheck (mypy)", ["mypy", "src"], project_root))
        if not self.skip_tests:
            stages.append(
                self._stage(
                    "tests (pytest)",
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-x",
                        "-q",
                        "--tb=short",
                        "-m",
                        "not real_provider",
                    ],
                    project_root,
                )
            )
        if not self.skip_acceptance_gate:
            stages.append(self._acceptance_gate_stage(project_root))
        failures = [str(stage["summary"]) for stage in stages if not stage.get("ok")]
        return GateCommandResult(
            root=self.root,
            status="ready" if not failures else "blocked",
            mode="release",
            stages={"release": stages},
            next_actions=(
                []
                if not failures
                else [
                    "Fix the failing release gate stages before releasing.",
                    *[f"{stage['name']}: {stage['summary']}" for stage in stages if not stage.get("ok")],
                ]
            ),
        )

    def _acceptance_gate_stage(self, cwd: Path) -> dict[str, Any]:
        if self.report_path is None or not self.report_path.exists():
            return {
                "name": "acceptance-gate",
                "ok": False,
                "summary": (
                    "No acceptance report provided. "
                    "Run `asteria /acceptance --suite core` first."
                ),
                "returncode": 1,
                "output": "",
            }
        return self._stage(
            "acceptance-gate",
            [
                sys.executable,
                "-m",
                "asteria_runtime",
                "/acceptance-gate",
                "--root",
                str(self.root),
                "--report",
                str(self.report_path),
                "--suite",
                self.suite,
            ],
            cwd,
            success_summary="Acceptance gate passed.",
            failure_summary="Acceptance gate failed",
        )

    def _stage(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        *,
        success_summary: str | None = None,
        failure_summary: str | None = None,
    ) -> dict[str, Any]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        ok = completed.returncode == 0
        return {
            "name": name,
            "ok": ok,
            "summary": (
                success_summary
                if ok and success_summary
                else f"{name} passed."
                if ok
                else f"{failure_summary or name} (exit {completed.returncode})."
            ),
            "returncode": completed.returncode,
            "output": completed.stdout + completed.stderr,
        }

    def _find_project_root(self) -> Path:
        candidate = Path(__file__).resolve()
        for parent in candidate.parents:
            if (parent / "pyproject.toml").exists() or (parent / "setup.py").exists():
                return parent
        return Path.cwd()

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
