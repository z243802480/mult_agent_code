from __future__ import annotations

import os
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


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
    report_path: Path | None = None

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
        if self.report_path:
            lines.append(f"Report: {self.report_path}")
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
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> AcceptanceResult:
        acceptance_dir = self.root / ".agent" / "acceptance"
        acceptance_dir.mkdir(parents=True, exist_ok=True)
        summary_json = self.summary_json or acceptance_dir / "latest_summary.json"
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
            "--summary-json",
            str(summary_json.resolve()),
        ]
        for scenario in self.scenarios:
            command.extend(["--scenario", scenario])
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
        report_path = acceptance_dir / "acceptance_report.json"
        self.store.write(
            report_path,
            self._build_report(completed.returncode, summary_json, completed.stdout, completed.stderr),
            "acceptance_report",
        )
        return AcceptanceResult(
            suite=self.suite,
            scenarios=self.scenarios,
            root=self.root,
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            summary_json=summary_json,
            report_path=report_path,
        )

    def _build_report(
        self,
        returncode: int,
        summary_json: Path,
        stdout: str,
        stderr: str,
    ) -> dict:
        summary = self._read_json(summary_json)
        scenarios = []
        for scenario in summary.get("scenarios", []):
            scenarios.append(
                {
                    "scenario": str(scenario.get("scenario") or "unknown"),
                    "ok": bool(scenario.get("ok", False)),
                    "workspace": scenario.get("workspace"),
                    "failure_summary": self._failure_summary(scenario),
                    "stdout_tail": self._tail(str(scenario.get("stdout") or "")),
                    "stderr_tail": self._tail(str(scenario.get("stderr") or "")),
                    "summary": scenario.get("summary"),
                }
            )
        if not scenarios and returncode != 0:
            scenarios.append(
                {
                    "scenario": "acceptance_command",
                    "ok": False,
                    "workspace": str(self.root),
                    "failure_summary": self._tail(stderr or stdout or "acceptance failed"),
                    "stdout_tail": self._tail(stdout),
                    "stderr_tail": self._tail(stderr),
                    "summary": summary or None,
                }
            )
        return {
            "schema_version": "0.1.0",
            "suite": self.suite,
            "requested_scenarios": self.scenarios,
            "root": str(self.root),
            "ok": returncode == 0,
            "returncode": returncode,
            "created_at": now_iso(),
            "summary_json": str(summary_json),
            "scenarios": scenarios,
        }

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _failure_summary(self, scenario: dict) -> str:
        if scenario.get("ok"):
            return ""
        failures = scenario.get("failures")
        if isinstance(failures, list) and failures:
            return "; ".join(str(item) for item in failures)
        summary = scenario.get("summary")
        if isinstance(summary, dict):
            error = summary.get("error")
            if error:
                return str(error)
        stderr = str(scenario.get("stderr") or "").strip()
        stdout = str(scenario.get("stdout") or "").strip()
        return self._tail(stderr or stdout or "scenario failed")

    def _tail(self, value: str, max_chars: int = 4000) -> str:
        if len(value) <= max_chars:
            return value
        return value[-max_chars:]

    def _command_timeout_seconds(self) -> int:
        return self.scenario_timeout_seconds * max(1, len(self.scenarios) or 1) + 60

    def _script_path(self) -> Path:
        return self._repo_root() / "scripts" / "real_model_acceptance.py"

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]
