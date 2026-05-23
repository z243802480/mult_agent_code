from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReleaseStage:
    name: str
    ok: bool
    summary: str
    returncode: int = 0
    output: str = ""


@dataclass(frozen=True)
class ReleaseCommandResult:
    root: Path
    ok: bool
    status: str
    stages: list[ReleaseStage] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "ok": self.ok,
            "status": self.status,
            "stages": [
                {
                    "name": stage.name,
                    "ok": stage.ok,
                    "summary": stage.summary,
                    "returncode": stage.returncode,
                }
                for stage in self.stages
            ],
            "failures": self.failures,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            "Release Gate",
            f"Root: {self.root}",
            f"Status: {self.status}",
            "",
            "Stages:",
        ]
        for stage in self.stages:
            icon = "[pass]" if stage.ok else "[fail]"
            lines.append(f"  {icon} {stage.name}: {stage.summary}")
        if self.failures:
            lines.extend(["", "Failures:"])
            lines.extend(f"  - {failure}" for failure in self.failures)
        if self.next_actions:
            lines.extend(["", "Next actions:"])
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class ReleaseCommand:
    """Wrap ruff, mypy, pytest, and acceptance-gate into one release check."""

    def __init__(
        self,
        root: Path,
        report_path: Path | None = None,
        suite: str = "core",
        skip_lint: bool = False,
        skip_typecheck: bool = False,
        skip_tests: bool = False,
        skip_gate: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.report_path = report_path
        self.suite = suite
        self.skip_lint = skip_lint
        self.skip_typecheck = skip_typecheck
        self.skip_tests = skip_tests
        self.skip_gate = skip_gate

    def run(self) -> ReleaseCommandResult:
        stages: list[ReleaseStage] = []
        project_root = self._find_project_root()

        if not self.skip_lint:
            stages.append(self._run_ruff(project_root))
        if not self.skip_typecheck:
            stages.append(self._run_mypy(project_root))
        if not self.skip_tests:
            stages.append(self._run_pytest(project_root))
        if not self.skip_gate:
            stages.append(self._run_acceptance_gate(project_root))

        failures = [stage.summary for stage in stages if not stage.ok]
        ok = not failures
        status = "ready" if ok else "blocked"
        next_actions: list[str] = []
        if not ok:
            next_actions.append("Fix the failing stages before releasing.")
            for stage in stages:
                if not stage.ok and stage.output:
                    next_actions.append(f"  {stage.name}: see output above for details.")

        return ReleaseCommandResult(
            root=self.root,
            ok=ok,
            status=status,
            stages=stages,
            failures=failures,
            next_actions=next_actions,
        )

    def _run_ruff(self, cwd: Path) -> ReleaseStage:
        result = self._run(["ruff", "check", "."], cwd)
        ok = result.returncode == 0
        return ReleaseStage(
            name="lint (ruff)",
            ok=ok,
            summary="Lint passed." if ok else f"Lint failed (exit {result.returncode}).",
            returncode=result.returncode,
            output=result.stdout + result.stderr,
        )

    def _run_mypy(self, cwd: Path) -> ReleaseStage:
        result = self._run(["mypy", "src"], cwd)
        ok = result.returncode == 0
        return ReleaseStage(
            name="typecheck (mypy)",
            ok=ok,
            summary=(
                "Type check passed."
                if ok
                else f"Type check failed (exit {result.returncode})."
            ),
            returncode=result.returncode,
            output=result.stdout + result.stderr,
        )

    def _run_pytest(self, cwd: Path) -> ReleaseStage:
        result = self._run(
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
            cwd,
        )
        ok = result.returncode == 0
        return ReleaseStage(
            name="tests (pytest)",
            ok=ok,
            summary="Tests passed." if ok else f"Tests failed (exit {result.returncode}).",
            returncode=result.returncode,
            output=result.stdout + result.stderr,
        )

    def _run_acceptance_gate(self, cwd: Path) -> ReleaseStage:
        if self.report_path is None or not self.report_path.exists():
            return ReleaseStage(
                name="acceptance-gate",
                ok=False,
                summary=(
                    "No acceptance report provided. "
                    "Run `asteria /acceptance --suite core` first."
                ),
                returncode=1,
            )
        cmd = [
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
        ]
        result = self._run(cmd, cwd)
        ok = result.returncode == 0
        return ReleaseStage(
            name="acceptance-gate",
            ok=ok,
            summary=(
                "Acceptance gate passed."
                if ok
                else f"Acceptance gate failed (exit {result.returncode})."
            ),
            returncode=result.returncode,
            output=result.stdout + result.stderr,
        )

    def _find_project_root(self) -> Path:
        candidate = Path(__file__).resolve()
        for parent in candidate.parents:
            if (parent / "pyproject.toml").exists() or (parent / "setup.py").exists():
                return parent
        return Path.cwd()

    def _run(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
