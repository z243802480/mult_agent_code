from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.models.model_failure import model_failure_context_from_env


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    summary: str
    severity: str = "info"


@dataclass(frozen=True)
class DoctorResult:
    root: Path
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(check.severity == "error" and not check.ok for check in self.checks)

    def to_text(self) -> str:
        lines = [
            "Agent doctor",
            f"Root: {self.root}",
            f"Status: {'pass' if self.ok else 'fail'}",
            "Checks:",
        ]
        for check in self.checks:
            marker = "ok" if check.ok else check.severity
            lines.append(f"  - {check.name}: {marker} - {check.summary}")
        if not self.ok:
            lines.append("Next: fix error checks before running gray validation.")
        return "\n".join(lines)


class DoctorCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> DoctorResult:
        return DoctorResult(
            root=self.root,
            checks=[
                self._agent_dir_check(),
                self._agents_guidance_check(),
                self._policy_check(),
                self._git_check(),
                self._model_route_check("strong"),
                self._model_route_check("medium"),
                self._gate_report_check(),
            ],
        )

    def _agent_dir_check(self) -> DoctorCheck:
        path = self.root / ".agent"
        return DoctorCheck(
            "agent_dir",
            path.exists(),
            ".agent exists" if path.exists() else "workspace is not initialized",
            "error",
        )

    def _agents_guidance_check(self) -> DoctorCheck:
        path = self.root / "AGENTS.md"
        return DoctorCheck(
            "root_guidance",
            path.exists(),
            "AGENTS.md exists" if path.exists() else "AGENTS.md missing",
            "error",
        )

    def _policy_check(self) -> DoctorCheck:
        required = [
            self.root / ".agent" / "project.json",
            self.root / ".agent" / "policies.json",
        ]
        missing = [path.name for path in required if not path.exists()]
        return DoctorCheck(
            "runtime_config",
            not missing,
            "project and policy config present" if not missing else "missing: " + ", ".join(missing),
            "error",
        )

    def _git_check(self) -> DoctorCheck:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return DoctorCheck("git", False, f"git unavailable: {exc}", "warning")
        ok = completed.returncode == 0 and completed.stdout.strip() == "true"
        return DoctorCheck(
            "git",
            ok,
            "git worktree detected" if ok else "no git worktree; sandbox falls back to temp copy",
            "warning",
        )

    def _model_route_check(self, tier: str) -> DoctorCheck:
        provider = os.getenv(f"AGENT_MODEL_{tier.upper()}_PROVIDER")
        if not provider:
            return DoctorCheck(
                f"model_{tier}",
                False,
                f"AGENT_MODEL_{tier.upper()}_PROVIDER is not set",
                "warning",
            )
        context = model_failure_context_from_env(f"AGENT_MODEL_{tier.upper()}")
        return DoctorCheck(
            f"model_{tier}",
            True,
            f"{context.provider}/{context.model_name or 'model not set'} "
            f"at {context.base_url or 'base url not set'}",
            "info",
        )

    def _gate_report_check(self) -> DoctorCheck:
        path = self.root / ".agent" / "model" / "real_model_gate_report.json"
        return DoctorCheck(
            "real_model_gate",
            path.exists(),
            str(path) if path.exists() else "real model gate report missing",
            "warning",
        )
