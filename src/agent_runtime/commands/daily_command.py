from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass
class DailyBudgetGuard:
    max_actions: int
    max_model_calls: int
    max_tool_calls: int
    max_runtime_minutes: int
    max_repair_attempts: int
    max_failures: int = 1
    action_count: int = 0
    failure_count: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    repair_attempts: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def before_action(self) -> str | None:
        if self.action_count >= self.max_actions:
            return f"max_actions reached ({self.action_count}/{self.max_actions})"
        return self._budget_stop_reason()

    def after_action(self, result: dict[str, Any]) -> str | None:
        self.action_count += 1
        if result.get("status") == "fail":
            self.failure_count += 1
            if self.failure_count >= self.max_failures:
                return f"failure limit reached ({self.failure_count}/{self.max_failures})"
        return self._budget_stop_reason()

    def apply_delta(self, before: dict[str, int], after: dict[str, int]) -> None:
        self.model_calls += max(0, after.get("model_calls", 0) - before.get("model_calls", 0))
        self.tool_calls += max(0, after.get("tool_calls", 0) - before.get("tool_calls", 0))
        self.repair_attempts += max(
            0,
            after.get("repair_attempts", 0) - before.get("repair_attempts", 0),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_actions": self.max_actions,
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_runtime_minutes": self.max_runtime_minutes,
            "max_repair_attempts": self.max_repair_attempts,
            "max_failures": self.max_failures,
            "actions": self.action_count,
            "failures": self.failure_count,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "repair_attempts": self.repair_attempts,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
        }

    def remaining_timeout_seconds(self) -> float:
        total = max(0, self.max_runtime_minutes) * 60
        if total <= 0:
            return 0.0
        return max(0.0, total - (time.monotonic() - self.started_at))

    def _budget_stop_reason(self) -> str | None:
        elapsed_minutes = (time.monotonic() - self.started_at) / 60
        if elapsed_minutes >= self.max_runtime_minutes:
            return f"runtime budget reached ({elapsed_minutes:.2f}/{self.max_runtime_minutes} min)"
        if self.model_calls >= self.max_model_calls:
            return f"model call budget reached ({self.model_calls}/{self.max_model_calls})"
        if self.tool_calls >= self.max_tool_calls:
            return f"tool call budget reached ({self.tool_calls}/{self.max_tool_calls})"
        if self.repair_attempts >= self.max_repair_attempts:
            return (
                "repair attempt budget reached "
                f"({self.repair_attempts}/{self.max_repair_attempts})"
            )
        return None


@dataclass(frozen=True)
class DailyPlanResult:
    date: str
    plan_path: Path
    action_count: int
    summary: str

    def to_text(self) -> str:
        return "\n".join(
            [
                "Long-run plan",
                f"Cycle: {self.date}",
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
            "Long-run cycle",
            f"Cycle: {self.date}",
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
            "Long-run report",
            f"Cycle: {self.date}",
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
        objective: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_runtime_minutes = max_runtime_minutes
        self.max_repair_attempts = max_repair_attempts
        self.objective = objective
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
            "cycle_id": self.date,
            "schedule_type": "long_running_cycle",
            "root": str(self.root),
            "status": "ready" if actions else "idle",
            "created_at": now_iso(),
            "objective": self.objective or summary,
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
            "model_profile": self._model_profile_signal(agent_dir),
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

    def _model_profile_signal(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "model" / "capability_profile.json"
        if not path.exists():
            return {
                "status": "missing",
                "profile_count": 0,
                "weak_routes": [],
                "profile_path": None,
            }
        profile = self.store.read(path, "model_capability_profile")
        weak_routes = []
        for item in profile.get("profiles", []):
            if not isinstance(item, dict):
                continue
            if int(item.get("total_calls") or 0) < 2:
                continue
            if float(item.get("success_rate") or 0.0) >= 0.8:
                continue
            weak_routes.append(
                {
                    "provider": str(item.get("provider") or "unknown"),
                    "model": str(item.get("model") or "unknown"),
                    "purpose": str(item.get("purpose") or "unknown"),
                    "success_rate": float(item.get("success_rate") or 0.0),
                    "recommended_action": str(
                        item.get("recommended_action") or "review_route_before_scaling"
                    ),
                }
            )
        return {
            "status": "ready",
            "profile_count": int(profile.get("profile_count") or 0),
            "weak_routes": weak_routes[:5],
            "profile_path": str(path),
        }

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
                    "responsible_role": "Product",
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
                    "responsible_role": "Evaluator",
                }
            )
            return actions
        model_profile = signals.get("model_profile", {})
        weak_routes = model_profile.get("weak_routes") or []
        if weak_routes:
            labels = [
                f"{item['provider']}/{item['model']}:{item['purpose']}"
                for item in weak_routes[:3]
            ]
            actions.append(
                {
                    "kind": "model_route_review",
                    "command": "python -m agent_runtime /capability-report --root .",
                    "summary": "Review weak model routes before spending long-run budget: "
                    + ", ".join(labels),
                    "risk": "model_route_risk",
                    "recommended_action": weak_routes[0].get("recommended_action"),
                    "responsible_role": "Product",
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
                    "responsible_role": "Coder",
                }
            )
        elif int(tasks.get("blocked", 0)):
            actions.append(
                {
                    "kind": "debug_blocked_task",
                    "command": "python -m agent_runtime /debug --root . --max-repairs 1",
                    "summary": "Repair one blocked task using latest evidence.",
                    "risk": "repair_may_pause",
                    "responsible_role": "Debugger",
                }
            )
        else:
            model_profile = signals.get("model_profile", {})
            if model_profile.get("status") == "missing":
                summary = "Generate capability and model profile data before scaling long-run work."
            else:
                summary = "Summarize current production and model capability before widening scope."
            actions.append(
                {
                    "kind": "capability_report",
                    "command": "python -m agent_runtime /capability-report --root .",
                    "summary": summary,
                    "risk": "read_only",
                    "responsible_role": "Evaluator",
                }
            )
        return actions

    def _summary(self, signals: dict[str, Any], actions: list[dict[str, Any]]) -> str:
        if not actions:
            return "No daily action is currently required."
        action = actions[0]
        current = signals.get("current_run_id") or "none"
        if self.objective:
            return f"Selected {action['kind']} for long-run objective: {self.objective}"
        return f"Selected {action['kind']} for current run {current}."


class DailyRunCommand:
    def __init__(
        self,
        root: Path,
        *,
        date: str | None = None,
        execute: bool = False,
        max_actions: int = 1,
        max_model_calls: int = 20,
        max_tool_calls: int = 60,
        max_runtime_minutes: int = 60,
        max_repair_attempts: int = 2,
        objective: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.execute = execute
        self.max_actions = max_actions
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_runtime_minutes = max_runtime_minutes
        self.max_repair_attempts = max_repair_attempts
        self.objective = objective
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> DailyRunResult:
        plan_result = DailyPlanCommand(
            self.root,
            date=self.date,
            max_model_calls=self.max_model_calls,
            max_tool_calls=self.max_tool_calls,
            max_runtime_minutes=self.max_runtime_minutes,
            max_repair_attempts=self.max_repair_attempts,
            objective=self.objective,
        ).run()
        plan = self.store.read(plan_result.plan_path, "daily_plan")
        guard = DailyBudgetGuard(
            max_actions=self.max_actions,
            max_model_calls=self.max_model_calls,
            max_tool_calls=self.max_tool_calls,
            max_runtime_minutes=self.max_runtime_minutes,
            max_repair_attempts=self.max_repair_attempts,
        )
        results = []
        stop_reason = None
        for action in plan.get("actions", []):
            stop_reason = guard.before_action()
            if stop_reason:
                break
            result = self._run_action(action, guard)
            results.append(result)
            self._record_action_evidence(action, result, plan)
            stop_reason = guard.after_action(result)
            if stop_reason:
                break
        status = self._status(results, stop_reason)
        if not self.execute:
            stop_reason = "plan_only"
        if self.execute and any(item["status"] == "fail" for item in results):
            status = "blocked"
        report = {
            "schema_version": "0.1.0",
            "date": self.date,
            "cycle_id": self.date,
            "schedule_type": "long_running_cycle",
            "root": str(self.root),
            "status": status,
            "created_at": now_iso(),
            "plan_path": str(plan_result.plan_path),
            "executed": self.execute,
            "goal": self._goal(plan),
            "objective": str(plan.get("objective") or self.objective or self._goal(plan)),
            "progress": self._progress(results, plan),
            "stop_reason": stop_reason,
            "budget": guard.snapshot(),
            "results": results,
            "summary": self._summary(results),
            "risks": self._risks(results, stop_reason, plan),
            "model_profile": (plan.get("signals") or {}).get("model_profile", {}),
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

    def _run_action(self, action: dict[str, Any], guard: DailyBudgetGuard) -> dict[str, Any]:
        if not self.execute:
            return {
                "kind": action.get("kind"),
                "status": "planned",
                "summary": action.get("summary"),
                "command": action.get("command"),
                "risk": action.get("risk"),
                "responsible_role": action.get("responsible_role"),
            }
        command = [sys.executable, "-m", "agent_runtime", *self._command_args(action)]
        env = os.environ.copy()
        src_path = str((Path(__file__).resolve().parents[3] / "src").resolve())
        env["PYTHONPATH"] = (
            src_path
            if not env.get("PYTHONPATH")
            else os.pathsep.join([src_path, env["PYTHONPATH"]])
        )
        run_id = self._current_run_id()
        before = self._cost_snapshot(run_id)
        started_at = now_iso()
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=max(1.0, guard.remaining_timeout_seconds()),
            )
            after = self._cost_snapshot(run_id)
            guard.apply_delta(before, after)
            status = "pass" if completed.returncode == 0 else "fail"
            failure_type = None if status == "pass" else self._failure_type(action, completed.stderr)
            return {
                "kind": action.get("kind"),
                "status": status,
                "summary": action.get("summary"),
                "command": " ".join(command),
                "risk": action.get("risk"),
                "responsible_role": action.get("responsible_role"),
                "returncode": completed.returncode,
                "failure_type": failure_type,
                "started_at": started_at,
                "ended_at": now_iso(),
                "cost_delta": self._cost_delta(before, after),
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
        except subprocess.TimeoutExpired as exc:
            after = self._cost_snapshot(run_id)
            guard.apply_delta(before, after)
            return {
                "kind": action.get("kind"),
                "status": "fail",
                "summary": action.get("summary"),
                "command": " ".join(command),
                "risk": action.get("risk"),
                "responsible_role": action.get("responsible_role"),
                "returncode": None,
                "failure_type": "daily_timeout",
                "started_at": started_at,
                "ended_at": now_iso(),
                "cost_delta": self._cost_delta(before, after),
                "stdout_tail": self._tail(exc.stdout),
                "stderr_tail": self._tail(exc.stderr),
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
        if kind == "model_route_review":
            return ["/capability-report", "--root", str(self.root)]
        return ["/capability-report", "--root", str(self.root)]

    def _status(self, results: list[dict[str, Any]], stop_reason: str | None) -> str:
        if not results:
            return "idle"
        if not self.execute:
            return "planned"
        if any(item["status"] == "fail" for item in results):
            return "blocked"
        if stop_reason:
            return "paused"
        return "completed"

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
            return [
                "Inspect daily_report.md and the failing task_execution_evidence before retrying.",
                "Run `agent /replan` or `agent /debug` only after the failure type is understood.",
            ]
        return ["Review daily_report.md and continue with the next daily plan."]

    def _write_markdown(self, path: Path, report: dict[str, Any]) -> None:
        lines = [
            "# Daily Report",
            "",
            f"- Date: {report['date']}",
            f"- Cycle: {report.get('cycle_id') or report['date']}",
            f"- Schedule type: {report.get('schedule_type') or 'long_running_cycle'}",
            f"- Status: {report['status']}",
            f"- Executed: {report['executed']}",
            f"- Goal: {report['goal']}",
            f"- Objective: {report.get('objective') or report['goal']}",
            f"- Progress: {report['progress']['completed_actions']}/{report['progress']['planned_actions']} action(s)",
            f"- Stop reason: {report.get('stop_reason') or 'none'}",
            f"- Summary: {report['summary']}",
            "",
            "## Model Profile",
            "",
            f"- Status: {(report.get('model_profile') or {}).get('status', 'missing')}",
            f"- Profiles: {(report.get('model_profile') or {}).get('profile_count', 0)}",
            f"- Profile path: {(report.get('model_profile') or {}).get('profile_path') or 'none'}",
            "",
            "## Budget",
            "",
            f"- Runtime seconds: {report['budget']['elapsed_seconds']}",
            f"- Model calls: {report['budget']['model_calls']}/{report['budget']['max_model_calls']}",
            f"- Tool calls: {report['budget']['tool_calls']}/{report['budget']['max_tool_calls']}",
            f"- Repair attempts: {report['budget']['repair_attempts']}/{report['budget']['max_repair_attempts']}",
            "",
            "## Results",
            "",
        ]
        for result in report["results"]:
            evidence = result.get("evidence_path") or "none"
            failure = result.get("failure_type") or "none"
            role = result.get("responsible_role") or "unknown"
            lines.append(
                f"- {result.get('kind')}: {result.get('status')} [{role}] - "
                f"{result.get('summary')} "
                f"(failure={failure}; evidence={evidence})"
            )
        lines.extend(["", "## Risks", ""])
        lines.extend(f"- {item}" for item in report.get("risks", []))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in report["next_actions"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _goal(self, plan: dict[str, Any]) -> str:
        actions = plan.get("actions", [])
        if actions:
            return str(actions[0].get("summary") or plan.get("summary"))
        return str(plan.get("summary") or "Keep the autonomous runtime ready.")

    def _progress(self, results: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, int]:
        planned = len(plan.get("actions", []))
        completed = len([item for item in results if item.get("status") == "pass"])
        failed = len([item for item in results if item.get("status") == "fail"])
        return {
            "planned_actions": planned,
            "attempted_actions": len(results),
            "completed_actions": completed,
            "failed_actions": failed,
        }

    def _risks(
        self,
        results: list[dict[str, Any]],
        stop_reason: str | None,
        plan: dict[str, Any],
    ) -> list[str]:
        risks = []
        if stop_reason and stop_reason != "plan_only":
            risks.append(f"Daily run paused: {stop_reason}.")
        for result in results:
            if result.get("status") == "fail":
                risks.append(
                    f"{result.get('kind')} failed with "
                    f"{result.get('failure_type') or 'unknown_failure'}."
                )
        acceptance = (plan.get("signals") or {}).get("acceptance") or {}
        failed = acceptance.get("failed_scenarios") or []
        if failed:
            risks.append("Acceptance still has failing scenarios: " + ", ".join(failed[:5]))
        model_profile = (plan.get("signals") or {}).get("model_profile") or {}
        if model_profile.get("status") == "missing":
            risks.append("Model capability profile is missing; routing decisions lack history.")
        weak_routes = model_profile.get("weak_routes") or []
        if weak_routes:
            labels = [
                f"{item['provider']}/{item['model']}:{item['purpose']}"
                for item in weak_routes[:3]
            ]
            risks.append("Weak model routes need review: " + ", ".join(labels))
        return risks or ["No immediate daily automation risk was detected."]

    def _record_action_evidence(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        evidence = self._action_evidence(action, result, plan)
        daily_path = self.root / ".agent" / "daily" / self.date / "task_execution_evidence.jsonl"
        self.jsonl.append(daily_path, evidence, "task_execution_evidence")
        result["evidence_path"] = str(daily_path)
        run_id = self._current_run_id()
        if not run_id:
            return
        run_path = self.root / ".agent" / "runs" / run_id / "task_execution_evidence.jsonl"
        self.jsonl.append(run_path, evidence, "task_execution_evidence")
        result["run_evidence_path"] = str(run_path)

    def _action_evidence(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = self._current_run_id()
        existing = self.jsonl.read_all(
            self.root / ".agent" / "daily" / self.date / "task_execution_evidence.jsonl",
            "task_execution_evidence",
        )
        task_id = f"daily-{self.date}-{action.get('kind') or 'action'}"
        return {
            "schema_version": "0.1.0",
            "evidence_id": f"daily-task-execution-{len(existing) + 1:04d}",
            "run_id": run_id,
            "task_id": task_id,
            "status": "done" if result.get("status") == "pass" else result.get("status", "blocked"),
            "summary": str(result.get("summary") or action.get("summary") or "Daily action"),
            "failure_type": result.get("failure_type"),
            "task": {
                "title": str(action.get("summary") or action.get("kind") or "Daily action"),
                "task_kind": "daily_action",
                "acceptance": [
                    "Daily action completes within budget",
                    "Daily report contains evidence and next action",
                ],
                "expected_artifacts": [
                    str(self.root / ".agent" / "daily" / self.date / "daily_report.json")
                ],
                "expected_changed_files": [],
                "allowed_tools": ["run_command"],
            },
            "action": {
                "summary": action.get("summary"),
                "tool_count": 1 if self.execute else 0,
                "verification_count": 0,
                "completion_notes": result.get("status"),
                "command": result.get("command") or action.get("command"),
                "risk": action.get("risk"),
                "responsible_role": action.get("responsible_role"),
            },
            "candidate": {
                "workspace": str(self.root),
                "candidate_id": f"daily-{self.date}",
                "strategy": "daily_control_loop",
                "changed_files": [],
                "promoted_files": [],
                "daily_report": str(self.root / ".agent" / "daily" / self.date / "daily_report.json"),
            },
            "contract_check": {
                "ok": result.get("status") in {"pass", "planned"},
                "stop_reason": result.get("failure_type"),
                "returncode": result.get("returncode"),
            },
            "tool_results": [
                {
                    "ok": result.get("status") in {"pass", "planned"},
                    "summary": result.get("summary") or "",
                    "error": result.get("stderr_tail") if result.get("status") == "fail" else None,
                    "warnings": [],
                    "data": {
                        "kind": result.get("kind"),
                        "command": result.get("command"),
                        "cost_delta": result.get("cost_delta", {}),
                    },
                }
            ],
            "verification_results": [],
            "created_at": now_iso(),
        }

    def _current_run_id(self) -> str | None:
        try:
            return RunStore(self.root / ".agent", self.validator).current_session_id()
        except RuntimeError:
            return None

    def _cost_snapshot(self, run_id: str | None) -> dict[str, int]:
        if not run_id:
            return {"model_calls": 0, "tool_calls": 0, "repair_attempts": 0}
        path = self.root / ".agent" / "runs" / run_id / "cost_report.json"
        if not path.exists():
            return {"model_calls": 0, "tool_calls": 0, "repair_attempts": 0}
        report = self.store.read(path, "cost_report")
        return {
            "model_calls": int(report.get("model_calls") or 0),
            "tool_calls": int(report.get("tool_calls") or 0),
            "repair_attempts": int(report.get("repair_attempts") or 0),
        }

    def _cost_delta(self, before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {
            key: max(0, after.get(key, 0) - before.get(key, 0))
            for key in {"model_calls", "tool_calls", "repair_attempts"}
        }

    def _failure_type(self, action: dict[str, Any], stderr: str) -> str:
        lowered = stderr.lower()
        if "decision" in lowered and "pending" in lowered:
            return "pending_decision"
        if "json" in lowered:
            return "model_format_error"
        if action.get("kind") == "acceptance_failed_only":
            return "acceptance_failed"
        return "daily_action_failed"

    def _tail(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")[-4000:]
        return value[-4000:]


class DailyReportCommand:
    def __init__(
        self,
        root: Path,
        *,
        date: str | None = None,
        objective: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.date = date or now_iso()[:10]
        self.objective = objective
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> DailyReportResult:
        report_path = self.root / ".agent" / "daily" / self.date / "daily_report.json"
        if not report_path.exists():
            result = DailyRunCommand(
                self.root,
                date=self.date,
                execute=False,
                objective=self.objective,
            ).run()
            report_path = result.report_path
        report = self.store.read(report_path, "daily_report")
        return DailyReportResult(
            date=self.date,
            report_path=report_path,
            status=str(report["status"]),
            summary=str(report["summary"]),
            next_actions=[str(item) for item in report.get("next_actions", [])],
        )
