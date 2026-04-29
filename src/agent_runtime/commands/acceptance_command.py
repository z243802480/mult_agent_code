from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AcceptanceResult:
    suite: str
    scenarios: list[str]
    root: Path
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    summary_json: Path | None = None

    def to_text(self) -> str:
        lines = [
            "Acceptance",
            f"Suite: {self.suite}",
            f"Scenarios: {', '.join(self.scenarios) if self.scenarios else 'suite default'}",
            f"Root: {self.root}",
            f"Status: {'pass' if self.ok else 'fail'}",
        ]
        if self.summary_json:
            lines.append(f"Summary: {self.summary_json}")
        if self.stdout.strip():
            lines.extend(["", self.stdout.strip()])
        if self.stderr.strip():
            lines.extend(["", self.stderr.strip()])
        return "\n".join(lines)


class AcceptanceCommand:
    def __init__(
        self,
        root: Path,
        suite: str = "smoke",
        scenarios: list[str] | None = None,
        summary_json: Path | None = None,
        allow_fake: bool = False,
        cleanup: bool = False,
        run_attempts: int = 2,
        model_max_retries: int = 5,
        scenario_timeout_seconds: int = 1200,
    ) -> None:
        self.root = root.resolve()
        self.suite = suite
        self.scenarios = scenarios or []
        self.summary_json = summary_json
        self.allow_fake = allow_fake
        self.cleanup = cleanup
        self.run_attempts = run_attempts
        self.model_max_retries = model_max_retries
        self.scenario_timeout_seconds = scenario_timeout_seconds

    def run(self) -> AcceptanceResult:
        command = [
            sys.executable,
            str(self._script_path()),
            "--suite",
            self.suite,
            "--root",
            str(self.root),
            "--run-attempts",
            str(self.run_attempts),
            "--model-max-retries",
            str(self.model_max_retries),
            "--scenario-timeout-seconds",
            str(self.scenario_timeout_seconds),
        ]
        for scenario in self.scenarios:
            command.extend(["--scenario", scenario])
        if self.summary_json:
            command.extend(["--summary-json", str(self.summary_json.resolve())])
        if self.allow_fake:
            command.append("--allow-fake")
        if self.cleanup:
            command.append("--cleanup")

        env = os.environ.copy()
        src_path = str((self._repo_root() / "src").resolve())
        env["PYTHONPATH"] = (
            src_path
            if not env.get("PYTHONPATH")
            else os.pathsep.join([src_path, env["PYTHONPATH"]])
        )
        if self.allow_fake:
            env["AGENT_MODEL_PROVIDER"] = "fake"

        completed = subprocess.run(
            command,
            cwd=self._repo_root(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=self._command_timeout_seconds(),
        )
        return AcceptanceResult(
            suite=self.suite,
            scenarios=self.scenarios,
            root=self.root,
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            summary_json=self.summary_json,
        )

    def _command_timeout_seconds(self) -> int:
        return self.scenario_timeout_seconds * max(1, len(self.scenarios) or 1) + 60

    def _script_path(self) -> Path:
        return self._repo_root() / "scripts" / "real_model_acceptance.py"

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]
