from __future__ import annotations

import os
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.acceptance_history_command import AcceptanceHistoryCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.core.acceptance_catalog import acceptance_metadata_index
from asteria_runtime.core.failure_attribution import classify_failure_attribution
from asteria_runtime.core.task_contract import completion_contract
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


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
    trend_warnings: list[str] = field(default_factory=list)

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
        if self.trend_warnings:
            lines.append("Trend warnings:")
            lines.extend(f"  - {warning}" for warning in self.trend_warnings)
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
        failed_only: bool = False,
        workspace_root: Path | None = None,
        promoted_run_max_iterations: int | None = None,
        promoted_run_max_tasks_per_iteration: int = 1,
        fail_on_trend_warning: bool = False,
        warn_model_call_delta: int = 5,
        warn_duration_delta: float = 120.0,
        warn_repair_delta: int = 1,
        warn_context_compaction_delta: int = 1,
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
        self.failed_only = failed_only
        self.workspace_root = workspace_root
        self.promoted_run_max_iterations = promoted_run_max_iterations
        self.promoted_run_max_tasks_per_iteration = promoted_run_max_tasks_per_iteration
        self.fail_on_trend_warning = fail_on_trend_warning
        self.warn_model_call_delta = warn_model_call_delta
        self.warn_duration_delta = warn_duration_delta
        self.warn_repair_delta = warn_repair_delta
        self.warn_context_compaction_delta = warn_context_compaction_delta
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> AcceptanceResult:
        acceptance_dir = self.root / ".asteria" / "acceptance"
        acceptance_dir.mkdir(parents=True, exist_ok=True)
        scenarios = self._effective_scenarios()
        summary_json = self.summary_json or acceptance_dir / "latest_summary.json"
        completed = self._run_acceptance_script(scenarios, summary_json)
        report_path = acceptance_dir / "acceptance_report.json"
        report = self._build_report(
            completed.returncode, summary_json, completed.stdout, completed.stderr
        )
        trend_warnings = self._trend_warnings()
        report["trend_warnings"] = trend_warnings
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
                promoted_tasks = promoter.repair_task_ids or promoted_tasks
                report["repair_workflow"] = self._repair_workflow(
                    promoted_tasks=promoted_tasks,
                    promoted_scenarios=promoted_scenarios,
                    promotion_error=None,
                )
                self.store.write(report_path, report, "acceptance_report")
            except RuntimeError as exc:
                promotion_error = str(exc)
                report["repair_workflow"] = self._repair_workflow(
                    promoted_tasks=[],
                    promoted_scenarios=[],
                    promotion_error=promotion_error,
                )
                self.store.write(report_path, report, "acceptance_report")
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
            report["repair_workflow"] = self._repair_workflow(
                promoted_tasks=promoted_tasks,
                promoted_scenarios=promoted_scenarios,
                promotion_error=None,
                repair_run_id=repair_run_id,
                rerun_summary_json=rerun_summary_json,
                rerun_ok=rerun_ok,
                closed_failures=closed_failures,
                remaining_failures=remaining_failures,
            )
            self.store.write(report_path, report, "acceptance_report")
        effective_ok = completed.returncode == 0 or (
            rerun_ok is True and bool(promoted_tasks) and not remaining_failures
        )
        if effective_ok and self.fail_on_trend_warning and trend_warnings:
            effective_ok = False
        return AcceptanceResult(
            suite=self.suite,
            scenarios=scenarios,
            root=self.root,
            ok=effective_ok,
            returncode=0 if effective_ok else completed.returncode or 1,
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
            trend_warnings=trend_warnings,
        )

    def _run_acceptance_script(
        self,
        scenarios: list[str],
        summary_json: Path,
    ) -> subprocess.CompletedProcess[str]:
        workspace_root = self._workspace_root(summary_json)
        command = [
            *self._acceptance_runner_command(),
            "--suite",
            self.suite,
            "--root",
            str(workspace_root),
            "--run-attempts",
            str(self.run_attempts),
            "--model-max-retries",
            str(self.model_max_retries),
            "--scenario-timeout-seconds",
            str(self.scenario_timeout_seconds),
            "--summary-json",
            str(summary_json.resolve()),
            "--history-jsonl",
            str((self.root / ".asteria" / "acceptance" / "history.jsonl").resolve()),
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

    def _effective_scenarios(self) -> list[str]:
        if self.scenarios:
            return self.scenarios
        if not self.failed_only:
            return []
        report_path = self.root / ".asteria" / "acceptance" / "acceptance_report.json"
        if not report_path.exists():
            raise RuntimeError("Cannot use --failed-only before an acceptance report exists.")
        report = self.store.read(report_path, "acceptance_report")
        raw_closure = report.get("repair_closure")
        closure: dict[str, Any] = raw_closure if isinstance(raw_closure, dict) else {}
        remaining = [str(item) for item in closure.get("remaining_failures", [])]
        if remaining:
            return list(dict.fromkeys(remaining))
        failed = [
            str(scenario.get("scenario") or "")
            for scenario in report.get("scenarios", [])
            if isinstance(scenario, dict) and not scenario.get("ok", False)
        ]
        return [item for item in dict.fromkeys(failed) if item]

    def _workspace_root(self, summary_json: Path) -> Path:
        if self.workspace_root:
            workspace_root = self.workspace_root.resolve()
        else:
            workspace_root = (
                self.root / ".asteria" / "acceptance" / "workspaces" / summary_json.stem
            ).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        return workspace_root

    def _build_report(
        self,
        returncode: int,
        summary_json: Path,
        stdout: str,
        stderr: str,
    ) -> dict:
        summary = self._read_json(summary_json)
        scenarios = []
        metadata = acceptance_metadata_index(summary)
        for scenario in summary.get("scenarios", []):
            name = str(scenario.get("scenario") or "unknown")
            scenario_meta = metadata.get(name, {})
            scenarios.append(
                {
                    "scenario": name,
                    "capability": scenario.get("capability") or scenario_meta.get("capability"),
                    "tier": scenario.get("tier") or scenario_meta.get("tier"),
                    "ok": bool(scenario.get("ok", False)),
                    "workspace": scenario.get("workspace"),
                    "failure_summary": self._failure_summary(scenario),
                    "failure_attribution": self._failure_attribution(scenario),
                    "attempts": scenario.get("attempts", []),
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
                    "failure_attribution": self._failure_attribution(
                        {"stderr": stderr, "stdout": stdout, "attempts": []}
                    ),
                    "attempts": [],
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
            "aggregate": summary.get("aggregate", {}),
            "trend": summary.get("trend", {}),
            "scenario_metadata": summary.get("scenario_metadata", []),
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

    def _failure_attribution(self, scenario: dict) -> dict:
        return classify_failure_attribution(scenario)

    def _repair_workflow(
        self,
        *,
        promoted_tasks: list[str],
        promoted_scenarios: list[str],
        promotion_error: str | None,
        repair_run_id: str | None = None,
        rerun_summary_json: Path | None = None,
        rerun_ok: bool | None = None,
        closed_failures: list[str] | None = None,
        remaining_failures: list[str] | None = None,
    ) -> dict:
        return {
            "promoted_tasks": promoted_tasks,
            "promoted_scenarios": promoted_scenarios,
            "promotion_error": promotion_error,
            "repair_run_id": repair_run_id,
            "rerun_summary_json": str(rerun_summary_json) if rerun_summary_json else None,
            "rerun_ok": rerun_ok,
            "closed_failures": closed_failures or [],
            "remaining_failures": remaining_failures or [],
            "status": self._repair_workflow_status(
                promoted_tasks, promotion_error, rerun_ok, remaining_failures or []
            ),
        }

    def _repair_workflow_status(
        self,
        promoted_tasks: list[str],
        promotion_error: str | None,
        rerun_ok: bool | None,
        remaining_failures: list[str],
    ) -> str:
        if promotion_error:
            return "promotion_failed"
        if rerun_ok is True and not remaining_failures:
            return "closed"
        if rerun_ok is False:
            return "remaining_failures"
        if promoted_tasks:
            return "promoted"
        return "not_started"

    def _tail(self, value: str, max_chars: int = 4000) -> str:
        if len(value) <= max_chars:
            return value
        return value[-max_chars:]

    def _command_timeout_seconds(self, scenarios: list[str]) -> int:
        return self.scenario_timeout_seconds * self._selected_scenario_count(scenarios) + 60

    def _selected_scenario_count(self, scenarios: list[str]) -> int:
        if scenarios:
            return len(scenarios)
        return {
            "smoke": 1,
            "offline": 1,
            "core": 6,
            "advanced": 5,
            "nightly": 11,
        }.get(self.suite, 1)

    def _acceptance_runner_command(self) -> list[str]:
        script_path = self._repo_root() / "scripts" / "real_model_acceptance.py"
        if script_path.exists():
            return [sys.executable, str(script_path)]
        return [sys.executable, "-m", "asteria_runtime.real_model_acceptance"]

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _run_promoted_tasks(self) -> str:
        run_store = RunStore(self.root / ".asteria", self.validator)
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
        run_store = RunStore(self.root / ".asteria", self.validator)
        return run_store.current_session_id()

    def _trend_warnings(self) -> list[str]:
        history_path = self.root / ".asteria" / "acceptance" / "history.jsonl"
        return (
            AcceptanceHistoryCommand(
                self.root,
                limit=1,
                suite=self.suite,
                history_jsonl=history_path,
                warn_model_call_delta=self.warn_model_call_delta,
                warn_duration_delta=self.warn_duration_delta,
                warn_repair_delta=self.warn_repair_delta,
                warn_context_compaction_delta=self.warn_context_compaction_delta,
            )
            .run()
            .warnings
        )


class AcceptanceFailurePromoter:
    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(
            Path(__file__).resolve().parents[3] / "schemas"
        )
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.promoted_scenarios: list[str] = []
        self.repair_task_ids: list[str] = []

    def promote(self, report: dict) -> list[str]:
        self.promoted_scenarios = []
        self.repair_task_ids = []
        failed_scenarios = [
            scenario
            for scenario in report.get("scenarios", [])
            if isinstance(scenario, dict) and not scenario.get("ok", False)
        ]
        if not failed_scenarios:
            return []
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            InitCommand(self.root).run()
            agent_dir = self.root / ".asteria"
        run_store = RunStore(agent_dir, self.validator)
        run_id = self._ensure_repair_session(run_store, report)
        run_dir = run_store.run_dir(run_id)
        task_plan_path = run_dir / "task_plan.json"
        if not task_plan_path.exists():
            self._write_repair_seed_artifacts(run_store, report, run_id)

        task_plan = self.store.read(task_plan_path, "task_board")
        existing_tasks = task_plan["tasks"]
        existing_by_key = {self._dedupe_key(task): task for task in existing_tasks}
        existing_keys = set(existing_by_key)
        next_index = self._next_task_index(existing_tasks)
        promoted: list[str] = []
        for scenario in failed_scenarios:
            scenario_name = str(scenario.get("scenario") or "unknown")
            key = f"acceptance:{scenario_name.lower()}"
            if key in existing_keys:
                existing_task = existing_by_key[key]
                self.repair_task_ids.append(str(existing_task["task_id"]))
                self.promoted_scenarios.append(scenario_name)
                continue
            task_id = f"task-{next_index:04d}"
            next_index += 1
            evidence_path = self._write_failure_evidence(report, scenario, task_id)
            existing_tasks.append(
                self._task_from_scenario(task_id, report, scenario, evidence_path)
            )
            existing_keys.add(key)
            self._record_failure_memory(agent_dir, report, scenario, task_id, evidence_path)
            promoted.append(task_id)
            self.repair_task_ids.append(task_id)
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

    def _ensure_repair_session(self, run_store: RunStore, report: dict) -> str:
        run_id = run_store.current_session_id()
        if run_id and (run_store.run_dir(run_id) / "task_plan.json").exists():
            run = run_store.load_run(run_id)
            stale_repair_session = run.get("goal_id") == "goal-acceptance-repair" and run.get(
                "status"
            ) in {"completed", "paused", "cancelled"}
            if not stale_repair_session:
                return run_id
        run = run_store.create_run(
            f"asteria acceptance repair session for suite {report.get('suite')}",
            goal_id="goal-acceptance-repair",
        )
        self._write_repair_seed_artifacts(run_store, report, run["run_id"])
        run_store.set_current_session(run["run_id"], "acceptance_failure_promotion")
        return str(run["run_id"])

    def _write_repair_seed_artifacts(
        self,
        run_store: RunStore,
        report: dict,
        run_id: str,
    ) -> None:
        run_dir = run_store.run_dir(run_id)
        goal_spec = {
            "schema_version": "0.1.0",
            "goal_id": "goal-acceptance-repair",
            "original_goal": "Repair failed real-model acceptance scenarios.",
            "normalized_goal": (
                f"Repair failed acceptance scenarios for suite `{report.get('suite')}`."
            ),
            "goal_type": "codebase_improvement",
            "assumptions": ["Failure evidence and scenario workspaces are available locally."],
            "constraints": [
                "Do not read or write protected paths.",
                "Do not commit secrets.",
                "Repair only the acceptance failure cause.",
            ],
            "non_goals": ["Do not redesign unrelated runtime architecture."],
            "expanded_requirements": [
                {
                    "id": "req-acceptance-repair",
                    "priority": "must",
                    "description": "Promote failed acceptance scenarios into repair tasks.",
                    "source": "inferred",
                    "acceptance": ["Each failed scenario has evidence and a repair task."],
                }
            ],
            "target_outputs": ["repair_tasks", "acceptance_report"],
            "definition_of_done": [
                "Promoted scenario reruns pass or remaining failures are recorded."
            ],
            "verification_strategy": ["Run /acceptance with --rerun-promoted."],
            "budget": {"max_iterations": 3, "max_model_calls": 20},
        }
        task_plan = {"schema_version": "0.1.0", "tasks": []}
        cost_report = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "model_calls": 0,
            "tool_calls": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }
        self.store.write(run_dir / "goal_spec.json", goal_spec, "goal_spec")
        self.store.write(run_dir / "task_plan.json", task_plan, "task_board")
        self.store.write(run_dir / "cost_report.json", cost_report, "cost_report")
        run = run_store.load_run(run_id)
        run["goal_id"] = goal_spec["goal_id"]
        run["status"] = "running"
        run["current_phase"] = "PLAN"
        run["summary"] = "Acceptance repair session seeded for promoted failure tasks."
        run_store.update_run(run)

    def _task_from_scenario(
        self,
        task_id: str,
        report: dict,
        scenario: dict,
        evidence_path: Path,
    ) -> dict:
        scenario_name = str(scenario.get("scenario") or "unknown")
        repair_focus = self._repair_focus(scenario, str(report.get("suite") or "smoke"))
        failure_summary = str(scenario.get("failure_summary") or "acceptance scenario failed")
        description_parts = [
            f"Repair the failing real-model acceptance scenario `{scenario_name}`.",
            f"Suite: {report.get('suite')}",
            f"Capability: {repair_focus['capability']}",
            f"Failure: {failure_summary}",
            "Repair focus:",
            *[f"- {item}" for item in repair_focus["guidance"]],
            "Diagnostics:",
            f"- Acceptance report: {self.root / '.asteria' / 'acceptance' / 'acceptance_report.json'}",
            f"- Failure evidence: {evidence_path}",
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
        expected_artifacts = [evidence_path.relative_to(self.root).as_posix()]
        expected_artifacts.extend(repair_focus["expected_artifacts"])
        task: dict[str, Any] = {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "title": f"Repair acceptance scenario: {scenario_name}",
            "description": "\n\n".join(description_parts),
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": [
                f"`asteria acceptance` no longer fails for scenario `{scenario_name}`",
                f"The reproduction command succeeds: `{self._acceptance_cli_command(report, scenario_name)}`",
                *repair_focus["acceptance"],
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
            "expected_artifacts": expected_artifacts,
            "task_kind": "implementation",
            "expected_changed_files": repair_focus["expected_changed_files"],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": (
                f"Generated from acceptance report for {scenario_name}; "
                f"reproduce with: {self._acceptance_cli_command(report, scenario_name)}"
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = {
            "required": True,
            "allow_expected_failure": False,
            "commands": [
                *repair_focus["verification_commands"],
                self._acceptance_cli_command(report, scenario_name),
            ],
        }
        return task

    def _write_failure_evidence(self, report: dict, scenario: dict, task_id: str) -> Path:
        scenario_name = str(scenario.get("scenario") or "unknown")
        repair_focus = self._repair_focus(scenario, str(report.get("suite") or "smoke"))
        evidence_path = (
            self.root / ".asteria" / "acceptance" / "failures" / f"{self._slug(scenario_name)}.json"
        )
        evidence = {
            "schema_version": "0.1.0",
            "evidence_id": f"acceptance-failure-{self._slug(scenario_name)}",
            "suite": str(report.get("suite") or "unknown"),
            "scenario": scenario_name,
            "capability": repair_focus["capability"],
            "failure_summary": str(scenario.get("failure_summary") or "acceptance scenario failed"),
            "failure_attribution": scenario.get("failure_attribution") or {},
            "repair_focus": repair_focus,
            "acceptance_report": str(
                self.root / ".asteria" / "acceptance" / "acceptance_report.json"
            ),
            "summary_json": report.get("summary_json"),
            "workspace": scenario.get("workspace"),
            "transcript": self._transcript_path(scenario),
            "expected_file": self._expected_file(scenario),
            "stdout_tail": str(scenario.get("stdout_tail") or ""),
            "stderr_tail": str(scenario.get("stderr_tail") or ""),
            "reproduce": {
                "cli": self._acceptance_cli_command(report, scenario_name),
                "script": self._acceptance_script_command(report, scenario_name),
            },
            "promoted_task_id": task_id,
            "created_at": now_iso(),
        }
        self.store.write(evidence_path, evidence, "acceptance_failure_evidence")
        return evidence_path

    def _repair_focus(self, scenario: dict, suite: str) -> dict[str, Any]:
        scenario_name = str(scenario.get("scenario") or "unknown")
        capability = str(scenario.get("capability") or "unknown")
        expected_file = self._expected_file(scenario)
        base_command = (
            f"python -m asteria_runtime /acceptance --suite {suite} --scenario {scenario_name}"
        )
        focus: dict[str, Any] = {
            "capability": capability,
            "guidance": [
                "Start from the scenario workspace and transcript before editing unrelated code.",
                "Make the smallest change that closes this scenario, then rerun only this scenario.",
            ],
            "acceptance": [
                "The fix is scoped to the failed capability and does not widen unrelated behavior."
            ],
            "expected_changed_files": [],
            "expected_artifacts": [],
            "verification_commands": [base_command],
        }
        if capability == "multi_file_change" or scenario_name == "multi_file_todo_cli":
            if expected_file:
                focus["expected_artifacts"].append(expected_file)
            focus["guidance"].extend(
                [
                    "Verify the package layout, entrypoint, and cross-file imports together.",
                    "Exercise both add and list flows so storage and CLI modules integrate correctly.",
                ]
            )
            focus["acceptance"].extend(
                [
                    "The entrypoint and package modules are both present.",
                    '`python todo.py add "buy milk"` and `python todo.py list` work in the scenario workspace.',
                ]
            )
            focus["expected_changed_files"].extend(
                ["todo.py", "todo_app/__init__.py", "todo_app/cli.py", "todo_app/storage.py"]
            )
            focus["verification_commands"].insert(
                0,
                'python todo.py add "buy milk" && python todo.py list',
            )
        elif capability == "configuration_change" or scenario_name == "config_driven_report":
            if expected_file:
                focus["expected_artifacts"].append(expected_file)
            focus["guidance"].extend(
                [
                    "Treat report_config.json as the source of truth for inputs and outputs.",
                    "Verify CSV parsing, minimum_total filtering, currency formatting, and report.md output.",
                ]
            )
            focus["acceptance"].extend(
                [
                    "`report_from_config.py` reads report_config.json instead of hard-coding paths.",
                    "`report.md` reflects configured currency and minimum_total filtering.",
                ]
            )
            focus["expected_changed_files"].extend(["report_from_config.py", "report.md"])
            focus["verification_commands"].insert(
                0,
                "python report_from_config.py report_config.json",
            )
        return focus

    def _acceptance_cli_command(self, report: dict, scenario_name: str) -> str:
        suite = str(report.get("suite") or "smoke")
        return f"python -m asteria_runtime /acceptance --suite {suite} --scenario {scenario_name}"

    def _acceptance_script_command(self, report: dict, scenario_name: str) -> str:
        suite = str(report.get("suite") or "smoke")
        summary_json = str(report.get("summary_json") or ".asteria/acceptance/latest_summary.json")
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

    def _slug(self, value: str) -> str:
        allowed = []
        for character in value.lower():
            if character.isalnum():
                allowed.append(character)
            elif character in {"-", "_", "."}:
                allowed.append(character)
            else:
                allowed.append("-")
        slug = "".join(allowed).strip("-")
        return slug or "unknown"

    def _record_failure_memory(
        self,
        agent_dir: Path,
        report: dict,
        scenario: dict,
        task_id: str,
        evidence_path: Path,
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
                "evidence": str(evidence_path),
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
