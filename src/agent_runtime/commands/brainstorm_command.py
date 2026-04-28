from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.agents.brainstorm_agent import BrainstormAgent
from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class BrainstormResult:
    run_id: str
    report_path: Path
    markdown_path: Path
    candidate_count: int
    created_tasks: int
    created_decisions: int

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Brainstorm run: {self.run_id}",
                f"Candidates: {self.candidate_count}",
                f"Created tasks: {self.created_tasks}",
                f"Created decisions: {self.created_decisions}",
                f"Report: {self.report_path}",
                f"Markdown: {self.markdown_path}",
            ]
        )


class BrainstormCommand:
    def __init__(
        self,
        root: Path,
        goal: str | None = None,
        run_id: str | None = None,
        max_candidates: int = 5,
        apply: bool = False,  # noqa: A002 - CLI flag is intentionally named --apply
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.run_id = run_id
        self.max_candidates = max_candidates
        self.apply = apply
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> BrainstormResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        project_config = self.store.read(agent_dir / "project.json", "project_config")
        run_store = RunStore(agent_dir, self.validator)
        run = self._load_or_create_run(run_store)
        run_id = run["run_id"]
        run_dir = run_store.run_dir(run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(policy, self._read_cost(cost_report_path, run_id), run_id=run_id)

        goal = self._goal_text(run_dir)
        run["status"] = "running"
        run["current_phase"] = "BRAINSTORM"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "BrainstormCommand", "INIT -> BRAINSTORM")

        report = BrainstormAgent(self._model_client(run_dir, budget), self.validator).generate(
            goal,
            project_context={
                "project": project_config,
                "existing_goal_spec": self._read_optional_json(run_dir / "goal_spec.json", "goal_spec"),
                "existing_task_plan": self._read_optional_json(run_dir / "task_plan.json", "task_board"),
                "policy": {
                    "decision_granularity": policy["decision_granularity"],
                    "budgets": policy["budgets"],
                    "permissions": policy["permissions"],
                },
            },
            run_id=run_id,
            max_candidates=self.max_candidates,
        )
        report_path = run_dir / "brainstorm_report.json"
        markdown_path = run_dir / "brainstorm_report.md"
        self.store.write(report_path, report, "brainstorm_report")
        markdown_path.write_text(self._markdown(report), encoding="utf-8")

        created_tasks = 0
        created_decisions = 0
        if self.apply:
            created_tasks = self._apply_tasks(agent_dir, run_dir, report)
            created_decisions = self._apply_decisions(run_dir, report)
            for _ in range(created_decisions):
                budget.record_user_decision()
            if created_tasks:
                event_logger.record(
                    run_id,
                    "task_created",
                    "BrainstormCommand",
                    f"Created {created_tasks} task(s) from brainstorm report",
                )
            if created_decisions:
                event_logger.record(
                    run_id,
                    "decision_created",
                    "BrainstormCommand",
                    f"Created {created_decisions} decision point(s) from brainstorm report",
                )

        event_logger.record(
            run_id,
            "artifact_created",
            "BrainstormAgent",
            f"Brainstorm report created with {len(report['candidates'])} candidate(s)",
            {"path": "brainstorm_report.json", "applied": self.apply},
        )
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")
        if created_decisions:
            run["status"] = "paused"
            run["current_phase"] = "DECIDE"
        else:
            run["current_phase"] = "BRAINSTORM"
        run["summary"] = report["summary"]
        run_store.update_run(run)
        run_store.set_current_session(run_id, "brainstorm_created")
        return BrainstormResult(
            run_id=run_id,
            report_path=report_path,
            markdown_path=markdown_path,
            candidate_count=len(report["candidates"]),
            created_tasks=created_tasks,
            created_decisions=created_decisions,
        )

    def _load_or_create_run(self, run_store: RunStore) -> dict:
        if self.run_id:
            return run_store.load_run(self.run_id)
        current = run_store.current_session_id()
        if current:
            return run_store.load_run(current)
        if not self.goal:
            raise RuntimeError("No current session found. Provide a goal or run `agent new \"goal\"` first.")
        return run_store.create_run(f'agent brainstorm "{self.goal}"')

    def _goal_text(self, run_dir: Path) -> str:
        if self.goal:
            return self.goal
        goal_spec = self._read_optional_json(run_dir / "goal_spec.json", "goal_spec")
        if goal_spec:
            return str(goal_spec["normalized_goal"])
        return "Explore viable directions for the current project."

    def _apply_tasks(self, agent_dir: Path, run_dir: Path, report: dict) -> int:
        candidates = report.get("task_candidates", [])
        if not candidates:
            return 0
        task_plan_path = run_dir / "task_plan.json"
        if task_plan_path.exists():
            task_plan = self.store.read(task_plan_path, "task_board")
        else:
            task_plan = {"schema_version": "0.1.0", "tasks": []}
        existing = task_plan["tasks"]
        created: list[dict] = []
        for candidate in candidates:
            task = self._task_from_candidate(candidate, existing + created)
            self.validator.validate("task", task)
            created.append(task)
        task_plan["tasks"].extend(created)
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        return len(created)

    def _apply_decisions(self, run_dir: Path, report: dict) -> int:
        candidates = report.get("decision_candidates", [])
        if not candidates:
            return 0
        path = run_dir / "decisions.jsonl"
        existing = self.jsonl.read_all(path, "decision_point") if path.exists() else []
        for index, candidate in enumerate(candidates, start=len(existing) + 1):
            decision = {
                "schema_version": "0.1.0",
                "decision_id": f"decision-{index:04d}",
                "status": "pending",
                "question": candidate["question"],
                "recommended_option_id": candidate["recommended_option_id"],
                "options": candidate["options"],
                "default_option_id": candidate["default_option_id"],
                "impact": candidate["impact"],
                "selected_option_id": None,
                "created_at": now_iso(),
                "resolved_at": None,
            }
            self.validator.validate("decision_point", decision)
            self.jsonl.append(path, decision, "decision_point")
        return len(candidates)

    def _task_from_candidate(self, candidate: dict, existing_tasks: list[dict]) -> dict:
        next_index = self._next_task_index(existing_tasks)
        dependency = self._last_active_task_id(existing_tasks)
        return {
            "schema_version": "0.1.0",
            "task_id": f"task-{next_index:04d}",
            "title": self._title(candidate["title"]),
            "description": candidate["description"],
            "status": "ready" if dependency is None else "backlog",
            "priority": candidate["priority"],
            "role": candidate["role"],
            "depends_on": [] if dependency is None else [dependency],
            "acceptance": candidate["acceptance"],
            "allowed_tools": [
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "run_tests",
            ],
            "expected_artifacts": candidate["expected_artifacts"],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": "Generated from brainstorm report",
        }

    def _read_optional_json(self, path: Path, schema_name: str) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _model_client(self, run_dir: Path, budget: BudgetController) -> ModelClient:
        if self.model_client:
            return MeteredModelClient(self.model_client, budget, ModelCallLogger(run_dir, self.validator))
        return create_model_client(run_dir, self.validator, budget)

    def _read_cost(self, path: Path, run_id: str) -> dict:
        if path.exists():
            return self.store.read(path, "cost_report")
        return {
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

    def _markdown(self, report: dict) -> str:
        lines = [
            "# Brainstorm Report",
            "",
            f"- Goal: {report['goal']}",
            f"- Summary: {report['summary']}",
            f"- Recommendation: {report['recommendation']['candidate_id']} - {report['recommendation']['reason']}",
            "",
            "## Candidates",
            "",
        ]
        for candidate in report["candidates"]:
            lines.append(f"- {candidate['candidate_id']}: {candidate['title']}")
        lines.extend(["", "## Task Candidates", ""])
        for task in report["task_candidates"]:
            lines.append(f"- {task['priority']}: {task['title']}")
        lines.extend(["", "## Decision Candidates", ""])
        for decision in report["decision_candidates"]:
            lines.append(f"- {decision['question']}")
        return "\n".join(lines) + "\n"

    def _next_task_index(self, tasks: list[dict]) -> int:
        indexes = []
        for task in tasks:
            suffix = task["task_id"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return (max(indexes) + 1) if indexes else 1

    def _last_active_task_id(self, tasks: list[dict]) -> str | None:
        active = [task["task_id"] for task in tasks if task["status"] != "discarded"]
        return active[-1] if active else None

    def _title(self, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."
