from __future__ import annotations

import os
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
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
    promoted_tasks: list[str] = field(default_factory=list)
    promotion_error: str | None = None
    promoted_run_text: str | None = None
    repair_run_id: str | None = None
    rerun_summary_json: Path | None = None
    rerun_ok: bool | None = None
    closed_failures: list[str] = field(default_factory=list)
    remaining_failures: list[str] = field(default_factory=list)

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
        if self.promoted_tasks:
            lines.append(f"Promoted failure tasks: {len(self.promoted_tasks)}")
            for task_id in self.promoted_tasks:
                lines.append(f"  - {task_id}")
        if self.promotion_error:
            lines.append(f"Promotion error: {self.promotion_error}")
        if self.promoted_run_text:
            lines.extend(["", "Promoted task run:", self.promoted_run_text])
        if self.rerun_ok is not None:
            lines.extend(
                [
                    "",
                    "Promoted failure rerun:",
                    f"Status: {'pass' if self.rerun_ok else 'fail'}",
                ]
            )
            if self.repair_run_id:
                lines.append(f"Repair run: {self.repair_run_id}")
            if self.rerun_summary_json:
                lines.append(f"Rerun summary: {self.rerun_summary_json}")
            if self.closed_failures:
                lines.append(f"Closed failures: {', '.join(self.closed_failures)}")
            if self.remaining_failures:
                lines.append(f"Remaining failures: {', '.join(self.remaining_failures)}")
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
        promote_failures: bool = False,
        run_promoted: bool = False,
        rerun_promoted: bool = False,
        promoted_run_max_iterations: int | None = None,
        promoted_run_max_tasks_per_iteration: int = 1,
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
        self.promote_failures = promote_failures
        self.run_promoted = run_promoted or rerun_promoted
        self.rerun_promoted = rerun_promoted
        self.promoted_run_max_iterations = promoted_run_max_iterations
        self.promoted_run_max_tasks_per_iteration = promoted_run_max_tasks_per_iteration
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> AcceptanceResult:
        acceptance_dir = self.root / ".agent" / "acceptance"
        acceptance_dir.mkdir(parents=True, exist_ok=True)
        summary_json = self.summary_json or acceptance_dir / "latest_summary.json"
        completed = self._run_acceptance_script(self.scenarios, summary_json)
        report_path = acceptance_dir / "acceptance_report.json"
        report = self._build_report(
            completed.returncode, summary_json, completed.stdout, completed.stderr
        )
        self.store.write(report_path, report, "acceptance_report")
        promoted_tasks = []
        promotion_error = None
        promoted_run_text = None
        repair_run_id = None
        rerun_summary_json = None
        rerun_ok = None
        closed_failures: list[str] = []
        remaining_failures: list[str] = []
        promoted_scenarios: list[str] = []
        if self.promote_failures and completed.returncode != 0:
            try:
                promoter = AcceptanceFailurePromoter(self.root, self.validator)
                promoted_tasks = promoter.promote(report)
                promoted_scenarios = promoter.promoted_scenarios
            except RuntimeError as exc:
                promotion_error = str(exc)
        if self.run_promoted and promoted_tasks and promotion_error is None:
            promoted_run_text = self._run_promoted_tasks()
            repair_run_id = self._current_run_id()
        if self.rerun_promoted and promoted_tasks and promotion_error is None:
            rerun_summary_json = acceptance_dir / "latest_promoted_rerun_summary.json"
            rerun_completed = self._run_acceptance_script(promoted_scenarios, rerun_summary_json)
            rerun_report = self._build_report(
                rerun_completed.returncode,
                rerun_summary_json,
                rerun_completed.stdout,
                rerun_completed.stderr,
            )
            rerun_ok = rerun_completed.returncode == 0
            remaining_failures = [
                str(scenario.get("scenario") or "unknown")
                for scenario in rerun_report.get("scenarios", [])
                if not scenario.get("ok", False)
            ]
            closed_failures = [
                scenario
                for scenario in promoted_scenarios
                if scenario not in set(remaining_failures)
            ]
            report["repair_closure"] = {
                "repair_run_id": repair_run_id,
                "rerun_summary_json": str(rerun_summary_json),
                "rerun_ok": rerun_ok,
                "closed_failures": closed_failures,
                "remaining_failures": remaining_failures,
            }
            self.store.write(report_path, report, "acceptance_report")
        effective_ok = completed.returncode == 0 or (
            rerun_ok is True and bool(promoted_tasks) and not remaining_failures
        )
        return AcceptanceResult(
            suite=self.suite,
            scenarios=self.scenarios,
            root=self.root,
            ok=effective_ok,
            returncode=0 if effective_ok else completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            summary_json=summary_json,
            report_path=report_path,
            promoted_tasks=promoted_tasks,
            promotion_error=promotion_error,
            promoted_run_text=promoted_run_text,
            repair_run_id=repair_run_id,
            rerun_summary_json=rerun_summary_json,
            rerun_ok=rerun_ok,
            closed_failures=closed_failures,
            remaining_failures=remaining_failures,
        )

    def _run_acceptance_script(
        self,
        scenarios: list[str],
        summary_json: Path,
    ) -> subprocess.CompletedProcess[str]:
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
        for scenario in scenarios:
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

        return subprocess.run(
            command,
            cwd=self._repo_root(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=self._command_timeout_seconds(scenarios),
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

    def _command_timeout_seconds(self, scenarios: list[str]) -> int:
        return self.scenario_timeout_seconds * max(1, len(scenarios) or 1) + 60

    def _script_path(self) -> Path:
        return self._repo_root() / "scripts" / "real_model_acceptance.py"

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _run_promoted_tasks(self) -> str:
        from agent_runtime.commands.run_command import RunCommand

        run_store = RunStore(self.root / ".agent", self.validator)
        run_id = run_store.current_session_id()
        if not run_id:
            raise RuntimeError("Cannot run promoted tasks: no current session found.")
        result = RunCommand(
            self.root,
            run_id=run_id,
            max_iterations=self.promoted_run_max_iterations,
            max_tasks_per_iteration=self.promoted_run_max_tasks_per_iteration,
        ).run()
        return result.to_text()

    def _current_run_id(self) -> str | None:
        run_store = RunStore(self.root / ".agent", self.validator)
        return run_store.current_session_id()


class AcceptanceFailurePromoter:
    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(
            Path(__file__).resolve().parents[3] / "schemas"
        )
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.promoted_scenarios: list[str] = []

    def promote(self, report: dict) -> list[str]:
        self.promoted_scenarios = []
        failed_scenarios = [
            scenario
            for scenario in report.get("scenarios", [])
            if isinstance(scenario, dict) and not scenario.get("ok", False)
        ]
        if not failed_scenarios:
            return []
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Cannot promote acceptance failures: workspace is not initialized.")
        run_store = RunStore(agent_dir, self.validator)
        run_id = run_store.current_session_id()
        if not run_id:
            raise RuntimeError("Cannot promote acceptance failures: no current session found.")
        run_dir = run_store.run_dir(run_id)
        task_plan_path = run_dir / "task_plan.json"
        if not task_plan_path.exists():
            raise RuntimeError(
                f"Cannot promote acceptance failures: missing task plan for {run_id}."
            )

        task_plan = self.store.read(task_plan_path, "task_board")
        existing_tasks = task_plan["tasks"]
        existing_keys = {self._dedupe_key(task) for task in existing_tasks}
        next_index = self._next_task_index(existing_tasks)
        promoted: list[str] = []
        for scenario in failed_scenarios:
            scenario_name = str(scenario.get("scenario") or "unknown")
            key = f"acceptance:{scenario_name.lower()}"
            if key in existing_keys:
                continue
            task_id = f"task-{next_index:04d}"
            next_index += 1
            existing_tasks.append(self._task_from_scenario(task_id, report, scenario))
            existing_keys.add(key)
            self._record_failure_memory(agent_dir, report, scenario, task_id)
            promoted.append(task_id)
            self.promoted_scenarios.append(scenario_name)

        if not promoted:
            return []
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        run = run_store.load_run(run_id)
        run["status"] = "running"
        run["current_phase"] = "PLAN"
        run["ended_at"] = None
        run["summary"] = f"Promoted {len(promoted)} acceptance failure task(s)."
        run_store.update_run(run)
        self._record_events(run_dir, run_id, promoted)
        return promoted

    def _task_from_scenario(self, task_id: str, report: dict, scenario: dict) -> dict:
        scenario_name = str(scenario.get("scenario") or "unknown")
        failure_summary = str(scenario.get("failure_summary") or "acceptance scenario failed")
        description_parts = [
            f"Repair the failing real-model acceptance scenario `{scenario_name}`.",
            f"Suite: {report.get('suite')}",
            f"Failure: {failure_summary}",
            "Diagnostics:",
            f"- Acceptance report: {self.root / '.agent' / 'acceptance' / 'acceptance_report.json'}",
            f"- Summary JSON: {report.get('summary_json')}",
            f"- Reproduce via CLI: {self._acceptance_cli_command(report, scenario_name)}",
            f"- Reproduce via script: {self._acceptance_script_command(report, scenario_name)}",
        ]
        workspace = scenario.get("workspace")
        if workspace:
            description_parts.append(f"- Scenario workspace: {workspace}")
        transcript = self._transcript_path(scenario)
        if transcript:
            description_parts.append(f"- Smoke transcript: {transcript}")
        expected_file = self._expected_file(scenario)
        if expected_file:
            description_parts.append(f"- Expected artifact: {expected_file}")
        stderr_tail = str(scenario.get("stderr_tail") or "").strip()
        if stderr_tail:
            description_parts.append(f"stderr tail:\n{stderr_tail}")
        return {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "title": f"Repair acceptance scenario: {scenario_name}",
            "description": "\n\n".join(description_parts),
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": [
                f"`agent acceptance` no longer fails for scenario `{scenario_name}`",
                f"The reproduction command succeeds: `{self._acceptance_cli_command(report, scenario_name)}`",
                "The fix is covered by deterministic tests or a documented verification command",
                "No protected paths, secrets, or destructive shell behavior are introduced",
            ],
            "allowed_tools": [
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "run_tests",
            ],
            "expected_artifacts": [],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": (
                f"Generated from acceptance report for {scenario_name}; "
                f"reproduce with: {self._acceptance_cli_command(report, scenario_name)}"
            ),
        }

    def _acceptance_cli_command(self, report: dict, scenario_name: str) -> str:
        suite = str(report.get("suite") or "smoke")
        return f"python -m agent_runtime /acceptance --suite {suite} --scenario {scenario_name}"

    def _acceptance_script_command(self, report: dict, scenario_name: str) -> str:
        suite = str(report.get("suite") or "smoke")
        summary_json = str(report.get("summary_json") or ".agent/acceptance/latest_summary.json")
        return (
            "python scripts/real_model_acceptance.py "
            f"--suite {suite} --scenario {scenario_name} --summary-json {summary_json}"
        )

    def _transcript_path(self, scenario: dict) -> str | None:
        summary = scenario.get("summary")
        if isinstance(summary, dict):
            transcript = summary.get("transcript")
            if transcript:
                return str(transcript)
        return None

    def _expected_file(self, scenario: dict) -> str | None:
        summary = scenario.get("summary")
        if isinstance(summary, dict):
            expected_file = summary.get("expected_file")
            if expected_file:
                return str(expected_file)
        return None

    def _record_events(self, run_dir: Path, run_id: str, task_ids: list[str]) -> None:
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            return
        logger = EventLogger(events_path, self.validator)
        logger.record(
            run_id,
            "acceptance_failures_promoted",
            "AcceptanceCommand",
            f"Promoted {len(task_ids)} acceptance failure task(s)",
            {"task_ids": task_ids},
        )

    def _next_task_index(self, tasks: list[dict]) -> int:
        indexes = []
        for task in tasks:
            suffix = str(task.get("task_id", "")).rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return max(indexes, default=0) + 1

    def _dedupe_key(self, task: dict) -> str:
        title = str(task.get("title") or "").lower()
        if title.startswith("repair acceptance scenario:"):
            return "acceptance:" + title.split(":", 1)[1].strip()
        notes = str(task.get("notes") or "").lower()
        marker = "generated from acceptance report for "
        if marker in notes:
            scenario = notes.split(marker, 1)[1].split(";", 1)[0].strip()
            return "acceptance:" + scenario
        return title

    def _record_failure_memory(
        self,
        agent_dir: Path,
        report: dict,
        scenario: dict,
        task_id: str,
    ) -> None:
        path = agent_dir / "memory" / "failures.jsonl"
        scenario_name = str(scenario.get("scenario") or "unknown")
        memory_key = self._memory_key(report, scenario_name)
        if memory_key in self._existing_memory_keys(path):
            return
        failure_summary = str(scenario.get("failure_summary") or "acceptance scenario failed")
        memory = {
            "schema_version": "0.1.0",
            "memory_id": self._next_memory_id(path),
            "type": "failure_lesson",
            "content": (
                f"Acceptance scenario `{scenario_name}` failed in suite `{report.get('suite')}`. "
                f"Failure summary: {failure_summary}. "
                f"Use `{self._acceptance_cli_command(report, scenario_name)}` to reproduce; "
                "repair task context includes report, summary, workspace, transcript, and expected artifact paths."
            ),
            "source": {
                "kind": "acceptance_report",
                "scenario": scenario_name,
                "suite": report.get("suite"),
                "summary_json": report.get("summary_json"),
                "workspace": scenario.get("workspace"),
                "task_id": task_id,
                "memory_key": memory_key,
            },
            "tags": [
                "acceptance",
                "failure",
                f"scenario:{scenario_name}",
                f"suite:{report.get('suite') or 'unknown'}",
            ],
            "confidence": 0.8,
            "created_at": now_iso(),
        }
        self.jsonl.append(path, memory, "memory_entry")

    def _memory_key(self, report: dict, scenario_name: str) -> str:
        return (
            f"{report.get('suite') or 'unknown'}:{scenario_name}:{report.get('summary_json') or ''}"
        )

    def _existing_memory_keys(self, path: Path) -> set[str]:
        return {
            str(entry.get("source", {}).get("memory_key"))
            for entry in self.jsonl.read_all(path, "memory_entry")
            if entry.get("source", {}).get("memory_key")
        }

    def _next_memory_id(self, path: Path) -> str:
        return f"memory-{len(self.jsonl.read_all(path, 'memory_entry')) + 1:04d}"
