from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.agents.goal_spec_agent import GoalSpecAgent
from agent_runtime.agents.planner import RequirementPlanner
from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class PlanResult:
    run_id: str
    goal_spec_path: Path
    task_plan_path: Path
    cost_report_path: Path
    task_count: int

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Created plan run: {self.run_id}",
                f"GoalSpec: {self.goal_spec_path}",
                f"Task plan: {self.task_plan_path}",
                f"Cost report: {self.cost_report_path}",
                f"Tasks: {self.task_count}",
            ]
        )


class PlanCommand:
    def __init__(
        self,
        root: Path,
        goal: str,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.model_client = model_client

    def run(self) -> PlanResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        project_config = self.store.read(agent_dir / "project.json", "project_config")
        run_store = RunStore(agent_dir, self.validator)
        run = run_store.create_run(f'agent plan "{self.goal}"')
        run_dir = run_store.run_dir(run["run_id"])
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        budget = BudgetController(policy, run_id=run["run_id"])
        if self.model_client:
            model_client = MeteredModelClient(
                self.model_client,
                budget,
                ModelCallLogger(run_dir, self.validator),
            )
        else:
            model_client = create_model_client(run_dir, self.validator, budget)

        event_logger.record(run["run_id"], "run_started", "PlanCommand", "Plan run started")
        event_logger.record(
            run["run_id"],
            "phase_changed",
            "PlanCommand",
            "INIT -> SPEC",
            {"from": "INIT", "to": "SPEC"},
        )

        goal_spec = GoalSpecAgent(model_client, self.validator).generate(
            self.goal,
            project_context={
                "project": project_config,
                "policy": {
                    "decision_granularity": policy["decision_granularity"],
                    "budgets": policy["budgets"],
                    "permissions": policy["permissions"],
                },
            },
            run_id=run["run_id"],
        )
        goal_spec_path = run_dir / "goal_spec.json"
        self.store.write(goal_spec_path, goal_spec, "goal_spec")
        event_logger.record(run["run_id"], "artifact_created", "GoalSpecAgent", "GoalSpec created")

        task_plan = RequirementPlanner().build_task_plan(goal_spec)
        for task in task_plan["tasks"]:
            self.validator.validate("task", task)
        task_plan_path = run_dir / "task_plan.json"
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        event_logger.record(
            run["run_id"],
            "task_created",
            "PlannerAgent",
            f"Created {len(task_plan['tasks'])} tasks",
        )

        cost_report = budget.cost_report()
        cost_report_path = run_dir / "cost_report.json"
        self.store.write(cost_report_path, cost_report, "cost_report")

        run["goal_id"] = goal_spec["goal_id"]
        run["current_phase"] = "PLAN"
        run["status"] = "completed"
        run["summary"] = f"Generated GoalSpec and {len(task_plan['tasks'])} tasks."
        run_store.update_run(run)
        event_logger.record(run["run_id"], "run_completed", "PlanCommand", run["summary"])

        return PlanResult(
            run_id=run["run_id"],
            goal_spec_path=goal_spec_path,
            task_plan_path=task_plan_path,
            cost_report_path=cost_report_path,
            task_count=len(task_plan["tasks"]),
        )
