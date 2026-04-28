from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class CompactResult:
    run_id: str | None
    snapshot_path: Path
    next_actions: list[str]

    def to_text(self) -> str:
        lines = [f"Created context snapshot: {self.snapshot_path}"]
        lines.append(f"Run: {self.run_id or 'none'}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {item}" for item in self.next_actions)
        return "\n".join(lines)


class CompactCommand:
    def __init__(self, root: Path, run_id: str | None = None, focus: str = "manual context compaction") -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.focus = focus
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> CompactResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        run_id = self.run_id or self._latest_run_id(agent_dir)
        run_dir = agent_dir / "runs" / run_id if run_id else None
        event_logger = None
        if run_dir and run_dir.exists():
            event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
            event_logger.record(run_id, "context_compacted", "CompactCommand", self.focus)

        snapshot = self._build_snapshot(agent_dir, run_id, run_dir)
        snapshots_dir = agent_dir / "context" / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshots_dir / f"{snapshot['snapshot_id']}.json"
        self.store.write(snapshot_path, snapshot, "context_snapshot")

        if run_dir and run_dir.exists():
            self._record_compaction_cost(run_dir, run_id)

        return CompactResult(run_id=run_id, snapshot_path=snapshot_path, next_actions=snapshot["next_actions"])

    def _build_snapshot(self, agent_dir: Path, run_id: str | None, run_dir: Path | None) -> dict:
        goal_spec = self._read_optional_json(run_dir / "goal_spec.json" if run_dir else None, "goal_spec")
        task_plan = self._read_optional_json(run_dir / "task_plan.json" if run_dir else None, "task_board")
        if not task_plan:
            task_plan = self._read_optional_json(agent_dir / "tasks" / "backlog.json", "task_board")
        cost_report = self._read_optional_json(run_dir / "cost_report.json" if run_dir else None, "cost_report")

        events = self._read_optional_jsonl(run_dir / "events.jsonl" if run_dir else None, "event")
        tool_calls = self._read_optional_jsonl(run_dir / "tool_calls.jsonl" if run_dir else None, "tool_call")
        model_calls = self._read_optional_jsonl(run_dir / "model_calls.jsonl" if run_dir else None, "model_call")

        tasks = task_plan.get("tasks", []) if task_plan else []
        active_tasks = [
            task["task_id"]
            for task in tasks
            if task["status"] in {"ready", "in_progress", "testing", "reviewing", "blocked"}
        ]
        modified_files = self._modified_files(tool_calls)
        failures = self._failures(tool_calls, events, model_calls)
        next_actions = self._next_actions(goal_spec, tasks, failures)

        snapshot_id = f"snapshot-{now_iso().replace(':', '').replace('-', '').replace('+', '-')}"
        return {
            "schema_version": "0.1.0",
            "snapshot_id": snapshot_id,
            "run_id": run_id,
            "created_at": now_iso(),
            "focus": self.focus,
            "goal_summary": goal_spec.get("normalized_goal") if goal_spec else "No GoalSpec available",
            "definition_of_done": goal_spec.get("definition_of_done", []) if goal_spec else [],
            "accepted_decisions": self._accepted_decisions(run_dir),
            "active_tasks": active_tasks,
            "modified_files": modified_files,
            "verification": self._verification(tool_calls),
            "failures": failures,
            "research_claims": [],
            "open_risks": self._open_risks(cost_report, failures),
            "next_actions": next_actions,
            "project": self._read_optional_json(agent_dir / "project.json", "project_config") or {},
        }

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted([path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name)
        return runs[-1].name if runs else None

    def _read_optional_json(self, path: Path | None, schema_name: str) -> dict:
        if path is None or not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _read_optional_jsonl(self, path: Path | None, schema_name: str) -> list[dict]:
        if path is None or not path.exists():
            return []
        return self.jsonl.read_all(path, schema_name)

    def _record_compaction_cost(self, run_dir: Path, run_id: str | None) -> None:
        path = run_dir / "cost_report.json"
        report = self._read_optional_json(path, "cost_report")
        if not report:
            report = {
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
        report["context_compactions"] = int(report.get("context_compactions", 0)) + 1
        self.store.write(path, report, "cost_report")

    def _modified_files(self, tool_calls: list[dict]) -> list[dict]:
        files = []
        for call in tool_calls:
            if call["tool_name"] not in {"write_file", "apply_patch"} or call["status"] != "success":
                continue
            files.append({"path": call["input_summary"], "reason": call["output_summary"]})
        return files[-20:]

    def _verification(self, tool_calls: list[dict]) -> list[dict]:
        checks = []
        for call in tool_calls:
            if call["tool_name"] in {"run_tests", "run_command"}:
                checks.append(
                    {
                        "command": call["input_summary"],
                        "status": "passed" if call["status"] == "success" else "failed",
                        "summary": call["output_summary"],
                    }
                )
        return checks[-10:]

    def _failures(self, tool_calls: list[dict], events: list[dict], model_calls: list[dict]) -> list[dict]:
        failures = []
        for call in tool_calls:
            if call["status"] != "success":
                failures.append({"summary": call["output_summary"], "status": call["status"]})
        for call in model_calls:
            if call["status"] != "success":
                failures.append({"summary": call["summary"], "status": call["status"]})
        for event in events:
            if event["type"] in {"error", "policy_denied", "budget_warning"}:
                failures.append({"summary": event["summary"], "status": event["type"]})
        return failures[-20:]

    def _accepted_decisions(self, run_dir: Path | None) -> list[str]:
        if not run_dir:
            return []
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        decisions = self.jsonl.read_all(path, "decision_point")
        accepted = []
        for decision in decisions:
            if decision["status"] in {"resolved", "defaulted"}:
                accepted.append(f"{decision['question']} -> {decision['selected_option_id'] or decision['default_option_id']}")
        return accepted

    def _open_risks(self, cost_report: dict, failures: list[dict]) -> list[str]:
        risks = []
        if failures:
            risks.append(f"{len(failures)} recent failure(s) need review")
        if cost_report and cost_report.get("status") in {"near_limit", "exceeded", "stopped"}:
            risks.append(f"Cost status is {cost_report['status']}")
        return risks

    def _next_actions(self, goal_spec: dict, tasks: list[dict], failures: list[dict]) -> list[str]:
        if failures:
            return ["Review recent failures", "Run /debug or repair workflow"]
        ready = [task for task in tasks if task["status"] == "ready"]
        if ready:
            return [f"Start task {ready[0]['task_id']}: {ready[0]['title']}"]
        if goal_spec:
            return ["Proceed to implementation or review based on task board"]
        return ["Run agent plan with a concrete goal"]
