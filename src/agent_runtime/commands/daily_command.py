from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class DailyPlanResult:
    date: str
    plan_path: Path
    action_count: int
    summary: str

    def to_text(self) -> str:
        return "\n".join(
            [
                "Daily plan",
                f"Date: {self.date}",
                f"Plan: {self.plan_path}",
                f"Actions: {self.action_count}",
                f"Summary: {self.summary}",
            ]
        )


@dataclass(frozen=True)
class DailyRunResult:
    date: str
    report_path: Path
    executed: bool
    status: str
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "Daily run",
            f"Date: {self.date}",
            f"Status: {self.status}",
            f"Executed: {self.executed}",
            f"Report: {self.report_path}",
        ]
        for result in self.results:
            lines.append(
                f"- {result.get('kind')}: {result.get('status')} - {result.get('summary')}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class DailyReportResult:
    date: str
    report_path: Path
    status: str
    summary: str
    next_actions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "Daily report",
            f"Date: {self.date}",
            f"Status: {self.status}",
            f"Report: {self.report_path}",
            f"Summary: {self.summary}",
        ]
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {item}" for item in self.next_actions)
        return "\n".join(lines)


class DailyPlanCommand:
    def __init__(
        self,
        root: Path,
        *,
        date: str | None = None,
        max_model_calls: int = 20,
        max_tool_calls: int = 60,
        max_runtime_minutes: int = 60,
        max_repair_attempts: int = 2,
    ) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_runtime_minutes = max_runtime_minutes
        self.max_repair_attempts = max_repair_attempts
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> DailyPlanResult:
        agent_dir = self._agent_dir()
        daily_dir = self._daily_dir(agent_dir)
        signals = self._signals(agent_dir)
        actions = self._actions(signals)
        summary = self._summary(signals, actions)
        plan = {
            "schema_version": "0.1.0",
            "date": self.date,
            "root": str(self.root),
            "status": "ready" if actions else "idle",
            "created_at": now_iso(),
            "summary": summary,
            "budget": {
                "max_model_calls": self.max_model_calls,
                "max_tool_calls": self.max_tool_calls,
                "max_runtime_minutes": self.max_runtime_minutes,
                "max_repair_attempts": self.max_repair_attempts,
            },
            "signals": signals,
            "actions": actions,
        }
        plan_path = daily_dir / "daily_plan.json"
        self.store.write(plan_path, plan, "daily_plan")
        return DailyPlanResult(
            date=self.date,
            plan_path=plan_path,
            action_count=len(actions),
            summary=summary,
        )

    def _agent_dir(self) -> Path:
        if not (self.root / ".agent").exists():
            InitCommand(self.root).run()
        return self.root / ".agent"

    def _daily_dir(self, agent_dir: Path) -> Path:
        path = agent_dir / "daily" / self.date
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _signals(self, agent_dir: Path) -> dict[str, Any]:
        acceptance = self._latest_acceptance(agent_dir)
        current_run = self._current_run(agent_dir)
        task_summary = self._task_summary(agent_dir, current_run)
        pending_decisions = self._pending_decisions(agent_dir, current_run)
        return {
            "current_run_id": current_run,
            "acceptance": acceptance,
            "task_summary": task_summary,
            "pending_decisions": pending_decisions,
        }

    def _latest_acceptance(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "acceptance" / "acceptance_report.json"
        if not path.exists():
            return {"status": "missing", "failed_scenarios": []}
        report = self.store.read(path, "acceptance_report")
        failed = [
            str(item.get("scenario") or "unknown")
            for item in report.get("scenarios", [])
            if isinstance(item, dict) and not item.get("ok", False)
        ]
        return {
            "status": "pass" if report.get("ok") else "fail",
            "suite": report.get("suite"),
            "failed_scenarios": failed,
            "report_path": str(path),
        }

    def _current_run(self, agent_dir: Path) -> str | None:
        try:
            return RunStore(agent_dir, self.validator).current_session_id()
        except RuntimeError:
            return None

    def _task_summary(self, agent_dir: Path, run_id: str | None) -> dict[str, Any]:
        if not run_id:
            return {"total": 0, "ready": 0, "blocked": 0}
        path = agent_dir / "runs" / run_id / "task_plan.json"
        if not path.exists():
            return {"total": 0, "ready": 0, "blocked": 0}
        board = self.store.read(path, "task_board")
        tasks = board.get("tasks", [])
        return {
            "total": len(tasks),
            "ready": len([task for task in tasks if task.get("status") == "ready"]),
            "blocked": len([task for task in tasks if task.get("status") == "blocked"]),
            "done": len([task for task in tasks if task.get("status") == "done"]),
        }

    def _pending_decisions(self, agent_dir: Path, run_id: str | None) -> list[dict[str, str]]:
        if not run_id:
            return []
        path = agent_dir / "runs" / run_id / "decisions.jsonl"
        decisions = self.jsonl.read_all(path, "decision_point") if path.exists() else []
        return [
            {
                "decision_id": str(decision.get("decision_id")),
                "question": str(decision.get("question")),
            }
            for decision in decisions
            if decision.get("status") == "pending"
        ]

    def _actions(self, signals: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        pending = signals.get("pending_decisions", [])
        if pending:
            actions.append(
                {
                    "kind": "resolve_decision",
                    "command": "python -m agent_runtime /decide --list-pending --root .",
                    "summary": f"Resolve pending decision {pending[0]['decision_id']}.",
                    "risk": "manual_input_required",
                }
            )
            return actions
        acceptance = signals.get("acceptance", {})
        failed = acceptance.get("failed_scenarios", [])
        if failed:
            actions.append(
                {
                    "kind": "acceptance_failed_only",
                    "command": "python -m agent_runtime /acceptance --root . --failed-only",
                    "summary": "Rerun only failed acceptance scenarios: " + ", ".join(failed[:5]),
                    "risk": "bounded_model_cost",
                }
            )
            return actions
        tasks = signals.get("task_summary", {})
        if int(tasks.get("ready", 0)):
            actions.append(
                {
                    "kind": "execute_ready_task",
                    "command": "python -m agent_runtime /execute --root . --max-tasks 1",
                    "summary": "Execute one ready task under the daily budget.",
                    "risk": "model_cost",
                }
            )
        elif int(tasks.get("blocked", 0)):
            actions.append(
                {
                    "kind": "debug_blocked_task",
                    "command": "python -m agent_runtime /debug --root . --max-repairs 1",
                    "summary": "Repair one blocked task using latest evidence.",
                    "risk": "repair_may_pause",
                }
            )
        else:
            actions.append(
                {
                    "kind": "capability_report",
                    "command": "python -m agent_runtime /capability-report --root .",
                    "summary": "Summarize current production capability and next risks.",
                    "risk": "read_only",
                }
            )
        return actions

    def _summary(self, signals: dict[str, Any], actions: list[dict[str, Any]]) -> str:
        if not actions:
            return "No daily action is currently required."
        action = actions[0]
        current = signals.get("current_run_id") or "none"
        return f"Selected {action['kind']} for current run {current}."


class DailyRunCommand:
    def __init__(
        self,
        root: Path,
        *,
        date: str | None = None,
        execute: bool = False,
        max_actions: int = 1,
    ) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.execute = execute
        self.max_actions = max_actions
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> DailyRunResult:
        plan_result = DailyPlanCommand(self.root, date=self.date).run()
        plan = self.store.read(plan_result.plan_path, "daily_plan")
        results = []
        for action in plan.get("actions", [])[: self.max_actions]:
            results.append(self._run_action(action))
        status = "completed" if all(item["status"] == "pass" for item in results) else "planned"
        if self.execute and any(item["status"] == "fail" for item in results):
            status = "blocked"
        report = {
            "schema_version": "0.1.0",
            "date": self.date,
            "root": str(self.root),
            "status": status,
            "created_at": now_iso(),
            "plan_path": str(plan_result.plan_path),
            "executed": self.execute,
            "results": results,
            "summary": self._summary(results),
            "next_actions": self._next_actions(results),
        }
        report_path = self.root / ".agent" / "daily" / self.date / "daily_report.json"
        self.store.write(report_path, report, "daily_report")
        self._write_markdown(report_path.with_suffix(".md"), report)
        return DailyRunResult(
            date=self.date,
            report_path=report_path,
            executed=self.execute,
            status=status,
            results=results,
        )

    def _run_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self.execute:
            return {
                "kind": action.get("kind"),
                "status": "planned",
                "summary": action.get("summary"),
                "command": action.get("command"),
            }
        command = [sys.executable, "-m", "agent_runtime", *self._command_args(action)]
        env = os.environ.copy()
        src_path = str((Path(__file__).resolve().parents[3] / "src").resolve())
        env["PYTHONPATH"] = (
            src_path
            if not env.get("PYTHONPATH")
            else os.pathsep.join([src_path, env["PYTHONPATH"]])
        )
        completed = subprocess.run(
            command,
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=3600,
        )
        return {
            "kind": action.get("kind"),
            "status": "pass" if completed.returncode == 0 else "fail",
            "summary": action.get("summary"),
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }

    def _command_args(self, action: dict[str, Any]) -> list[str]:
        kind = action.get("kind")
        if kind == "acceptance_failed_only":
            return ["/acceptance", "--root", str(self.root), "--failed-only"]
        if kind == "execute_ready_task":
            return ["/execute", "--root", str(self.root), "--max-tasks", "1"]
        if kind == "debug_blocked_task":
            return ["/debug", "--root", str(self.root), "--max-repairs", "1"]
        if kind == "resolve_decision":
            return ["/decide", "--root", str(self.root), "--list-pending"]
        return ["/capability-report", "--root", str(self.root)]

    def _summary(self, results: list[dict[str, Any]]) -> str:
        if not results:
            return "No daily action was selected."
        if not self.execute:
            return "Daily actions were planned but not executed. Pass --execute to run them."
        passed = len([item for item in results if item["status"] == "pass"])
        return f"Executed {len(results)} action(s), {passed} passed."

    def _next_actions(self, results: list[dict[str, Any]]) -> list[str]:
        if not self.execute:
            return ["Review the daily plan, then run `agent /daily-run --execute` if appropriate."]
        if any(item["status"] == "fail" for item in results):
            return ["Inspect daily_report.md and the failing command evidence before retrying."]
        return ["Review daily_report.md and continue with the next daily plan."]

    def _write_markdown(self, path: Path, report: dict[str, Any]) -> None:
        lines = [
            "# Daily Report",
            "",
            f"- Date: {report['date']}",
            f"- Status: {report['status']}",
            f"- Executed: {report['executed']}",
            f"- Summary: {report['summary']}",
            "",
            "## Results",
            "",
        ]
        for result in report["results"]:
            lines.append(f"- {result.get('kind')}: {result.get('status')} - {result.get('summary')}")
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in report["next_actions"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class DailyReportCommand:
    def __init__(self, root: Path, *, date: str | None = None) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> DailyReportResult:
        report_path = self.root / ".agent" / "daily" / self.date / "daily_report.json"
        if not report_path.exists():
            result = DailyRunCommand(self.root, date=self.date, execute=False).run()
            report_path = result.report_path
        report = self.store.read(report_path, "daily_report")
        return DailyReportResult(
            date=self.date,
            report_path=report_path,
            status=str(report["status"]),
            summary=str(report["summary"]),
            next_actions=[str(item) for item in report.get("next_actions", [])],
        )
