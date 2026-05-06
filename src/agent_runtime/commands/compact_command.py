from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
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
    def __init__(
        self, root: Path, run_id: str | None = None, focus: str = "manual context compaction"
    ) -> None:
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

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
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

        return CompactResult(
            run_id=run_id, snapshot_path=snapshot_path, next_actions=snapshot["next_actions"]
        )

    def _build_snapshot(self, agent_dir: Path, run_id: str | None, run_dir: Path | None) -> dict:
        goal_spec = self._read_optional_json(
            run_dir / "goal_spec.json" if run_dir else None, "goal_spec"
        )
        task_plan = self._read_optional_json(
            run_dir / "task_plan.json" if run_dir else None, "task_board"
        )
        if not task_plan:
            task_plan = self._read_optional_json(agent_dir / "tasks" / "backlog.json", "task_board")
        cost_report = self._read_optional_json(
            run_dir / "cost_report.json" if run_dir else None, "cost_report"
        )
        run_state = (
            self._read_optional_json(run_dir / "run.json" if run_dir else None, "run")
            if run_dir
            else {}
        )

        events = self._read_optional_jsonl(run_dir / "events.jsonl" if run_dir else None, "event")
        tool_calls = self._read_optional_jsonl(
            run_dir / "tool_calls.jsonl" if run_dir else None, "tool_call"
        )
        model_calls = self._read_optional_jsonl(
            run_dir / "model_calls.jsonl" if run_dir else None, "model_call"
        )
        artifacts = self._read_optional_jsonl(
            run_dir / "artifacts.jsonl" if run_dir else None, "artifact"
        )
        task_failures = self._read_optional_jsonl(
            run_dir / "task_failures.jsonl" if run_dir else None, "task_failure_evidence"
        )

        tasks = task_plan.get("tasks", []) if task_plan else []
        active_tasks = [
            task["task_id"]
            for task in tasks
            if task["status"] in {"ready", "in_progress", "testing", "reviewing", "blocked"}
        ]
        modified_files = self._modified_files(tool_calls, artifacts)
        failures = self._failures(tool_calls, events, model_calls)
        acceptance_failures = self._acceptance_failures(agent_dir)
        pending_decisions = self._pending_decisions(run_dir)
        report_summaries = self._report_summaries(run_dir)
        next_actions = self._next_actions(
            goal_spec,
            tasks,
            failures,
            pending_decisions,
            acceptance_failures,
        )

        snapshot_id = f"snapshot-{now_iso().replace(':', '').replace('-', '').replace('+', '-')}"
        return {
            "schema_version": "0.1.0",
            "snapshot_id": snapshot_id,
            "run_id": run_id,
            "created_at": now_iso(),
            "focus": self.focus,
            "goal_summary": goal_spec.get("normalized_goal")
            if goal_spec
            else "No GoalSpec available",
            "definition_of_done": goal_spec.get("definition_of_done", []) if goal_spec else [],
            "accepted_decisions": self._accepted_decisions(run_dir),
            "pending_decisions": pending_decisions,
            "run_status": self._run_status(run_state),
            "task_summary": self._task_summary(tasks),
            "active_tasks": active_tasks,
            "modified_files": modified_files,
            "recent_artifacts": self._recent_artifacts(artifacts, run_dir),
            "verification": self._verification(tool_calls),
            "verification_summary": self._latest_verification_summary(agent_dir),
            "failures": failures,
            "task_failures": self._task_failures(task_failures, run_dir),
            "acceptance_failures": acceptance_failures,
            "report_summaries": report_summaries,
            "research_claims": [],
            "open_risks": self._open_risks(
                cost_report, failures, task_failures, acceptance_failures
            ),
            "next_actions": next_actions,
            "project": self._read_optional_json(agent_dir / "project.json", "project_config") or {},
        }

    def _latest_verification_summary(self, agent_dir: Path) -> dict:
        path = agent_dir / "verification" / "latest.json"
        if not path.exists():
            return {}
        summary = self.store.read(path, "verification_summary")
        return {
            "status": summary["status"],
            "platform": summary["platform"],
            "created_at": summary["created_at"],
            "checks": summary.get("checks", []),
            "artifacts": summary.get("artifacts", {}),
        }

    def _acceptance_failures(self, agent_dir: Path) -> list[dict]:
        failures_dir = agent_dir / "acceptance" / "failures"
        if not failures_dir.exists():
            return []
        failures = []
        for path in sorted(failures_dir.glob("*.json")):
            evidence = self._read_optional_json(path, "acceptance_failure_evidence")
            if not evidence:
                continue
            failures.append(
                {
                    "scenario": evidence["scenario"],
                    "suite": evidence["suite"],
                    "failure_summary": evidence["failure_summary"],
                    "evidence_path": path.relative_to(self.root).as_posix(),
                    "promoted_task_id": evidence["promoted_task_id"],
                    "reproduce": evidence.get("reproduce", {}),
                    "created_at": evidence.get("created_at"),
                }
            )
        failures.sort(key=lambda item: str(item.get("created_at", "")))
        return failures[-10:]

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted(
            [path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name
        )
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

    def _modified_files(
        self, tool_calls: list[dict], artifacts: list[dict] | None = None
    ) -> list[dict]:
        if artifacts:
            return [
                {"path": artifact["path"], "reason": artifact["summary"]}
                for artifact in artifacts[-20:]
            ]
        files = []
        for call in tool_calls:
            if (
                call["tool_name"] not in {"write_file", "apply_patch"}
                or call["status"] != "success"
            ):
                continue
            files.append({"path": call["input_summary"], "reason": call["output_summary"]})
        return files[-20:]

    def _recent_artifacts(self, artifacts: list[dict], run_dir: Path | None) -> list[dict]:
        recent = [
            {
                "path": artifact["path"],
                "type": artifact["type"],
                "summary": artifact["summary"],
            }
            for artifact in artifacts[-20:]
        ]
        if not run_dir:
            return recent
        for filename, artifact_type in (
            ("goal_spec.json", "goal_spec"),
            ("task_plan.json", "task_plan"),
            ("review_report.md", "review_report"),
            ("final_report.md", "final_report"),
        ):
            path = run_dir / filename
            if path.exists() and not any(
                item["path"] == str(path.relative_to(self.root)) for item in recent
            ):
                recent.append(
                    {
                        "path": str(path.relative_to(self.root)),
                        "type": artifact_type,
                        "summary": f"{filename} exists",
                    }
                )
        return recent[-20:]

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

    def _failures(
        self, tool_calls: list[dict], events: list[dict], model_calls: list[dict]
    ) -> list[dict]:
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

    def _task_failures(self, task_failures: list[dict], run_dir: Path | None) -> list[dict]:
        failures = []
        for item in task_failures[-10:]:
            evidence_path = None
            if run_dir:
                evidence_path = (run_dir / "task_failures.jsonl").relative_to(self.root).as_posix()
            failures.append(
                {
                    "evidence_id": item["evidence_id"],
                    "task_id": item["task_id"],
                    "phase": item["phase"],
                    "failure_type": item["failure_type"],
                    "summary": item["summary"],
                    "contract_check": item.get("contract_check", {}),
                    "recommendations": item.get("recommendations", [])[:5],
                    "evidence_path": evidence_path,
                    "created_at": item.get("created_at"),
                }
            )
        return failures

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
                accepted.append(
                    f"{decision['question']} -> {decision['selected_option_id'] or decision['default_option_id']}"
                )
        return accepted

    def _pending_decisions(self, run_dir: Path | None) -> list[dict]:
        if not run_dir:
            return []
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        decisions = self.jsonl.read_all(path, "decision_point")
        return [
            {
                "decision_id": decision["decision_id"],
                "question": decision["question"],
                "recommended_option_id": decision["recommended_option_id"],
                "default_option_id": decision["default_option_id"],
            }
            for decision in decisions
            if decision["status"] == "pending"
        ]

    def _run_status(self, run_state: dict) -> dict:
        if not run_state:
            return {}
        return {
            "status": run_state.get("status"),
            "current_phase": run_state.get("current_phase"),
            "summary": run_state.get("summary"),
        }

    def _task_summary(self, tasks: list[dict]) -> dict:
        statuses = {
            "backlog": 0,
            "ready": 0,
            "in_progress": 0,
            "testing": 0,
            "reviewing": 0,
            "blocked": 0,
            "done": 0,
            "discarded": 0,
        }
        for task in tasks:
            status = str(task.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
        return {
            "total": len(tasks),
            "by_status": statuses,
            "remaining": sum(
                count for status, count in statuses.items() if status not in {"done", "discarded"}
            ),
        }

    def _report_summaries(self, run_dir: Path | None) -> dict:
        if not run_dir:
            return {}
        return {
            "review_report": self._markdown_excerpt(run_dir / "review_report.md"),
            "final_report": self._markdown_excerpt(run_dir / "final_report.md"),
        }

    def _markdown_excerpt(self, path: Path, max_lines: int = 12) -> str | None:
        if not path.exists():
            return None
        lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]
        meaningful = [line for line in lines if line.strip()]
        return "\n".join(meaningful[:max_lines])

    def _open_risks(
        self,
        cost_report: dict,
        failures: list[dict],
        task_failures: list[dict],
        acceptance_failures: list[dict],
    ) -> list[str]:
        risks = []
        if failures:
            risks.append(f"{len(failures)} recent failure(s) need review")
        if task_failures:
            latest = task_failures[-1]
            risks.append(
                f"{len(task_failures)} task failure evidence item(s) need repair "
                f"(latest: {latest.get('task_id')})"
            )
        if acceptance_failures:
            risks.append(
                f"{len(acceptance_failures)} acceptance failure evidence item(s) need repair"
            )
        if cost_report and cost_report.get("status") in {"near_limit", "exceeded", "stopped"}:
            risks.append(f"Cost status is {cost_report['status']}")
        return risks

    def _next_actions(
        self,
        goal_spec: dict,
        tasks: list[dict],
        failures: list[dict],
        pending_decisions: list[dict],
        acceptance_failures: list[dict],
    ) -> list[str]:
        if pending_decisions:
            return [f"Resolve decision {pending_decisions[0]['decision_id']} with /decide"]
        if acceptance_failures:
            scenario = acceptance_failures[-1]["scenario"]
            return [f"Repair acceptance failure evidence for {scenario}", "Run /debug or /execute"]
        if failures:
            return ["Review recent failures", "Run /debug or repair workflow"]
        blocked = [task for task in tasks if task["status"] == "blocked"]
        if blocked:
            return [f"Debug blocked task {blocked[0]['task_id']}: {blocked[0]['title']}"]
        ready = [task for task in tasks if task["status"] == "ready"]
        if ready:
            return [f"Start task {ready[0]['task_id']}: {ready[0]['title']}"]
        if tasks and all(task["status"] in {"done", "discarded"} for task in tasks):
            return ["Run review or acceptance to verify completed work"]
        if goal_spec:
            return ["Proceed to implementation or review based on task board"]
        return ["Run agent plan with a concrete goal"]
