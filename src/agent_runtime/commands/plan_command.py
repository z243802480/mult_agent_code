from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.agents.goal_spec_agent import GoalSpecAgent
from agent_runtime.agents.planner import RequirementPlanner
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.models.model_failure import (
    ModelFailureRecorder,
    model_failure_context_from_client,
)
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class PlanResult:
    run_id: str
    goal_spec_path: Path
    task_plan_path: Path
    task_plan_eval_path: Path
    cost_report_path: Path
    task_count: int
    task_plan_status: str
    task_plan_score: float

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Created plan run: {self.run_id}",
                f"GoalSpec: {self.goal_spec_path}",
                f"Task plan: {self.task_plan_path}",
                f"Task plan eval: {self.task_plan_eval_path}",
                f"Task plan quality: {self.task_plan_status} ({self.task_plan_score:.2f})",
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
        model_client: ModelClient
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
        runtime_context = ContextLoader(self.root, self.validator).load()

        try:
            goal_spec = GoalSpecAgent(model_client, self.validator).generate(
                self.goal,
                project_context={
                    "project": project_config,
                    "runtime_context": runtime_context,
                    "policy": {
                        "decision_granularity": policy["decision_granularity"],
                        "budgets": policy["budgets"],
                        "permissions": policy["permissions"],
                    },
                },
                run_id=run["run_id"],
            )
        except Exception as exc:  # noqa: BLE001 - plan records model-boundary diagnostics before re-raise
            context = model_failure_context_from_client(model_client, model_tier="strong")
            report_path, report = ModelFailureRecorder(self.root, self.validator).record(
                provider=context.provider,
                model_name=context.model_name,
                base_url=context.base_url,
                error=exc,
            )
            run["current_phase"] = "SPEC"
            run["status"] = "failed"
            run["ended_at"] = now_iso()
            run["summary"] = (
                f"GoalSpec model call failed with {report['failure_type']}. "
                f"Failure report: {report_path}"
            )
            run_store.update_run(run)
            event_logger.record(
                run["run_id"],
                "run_failed",
                "GoalSpecAgent",
                run["summary"],
                {"failure_report": str(report_path), "failure_type": report["failure_type"]},
            )
            raise RuntimeError(run["summary"]) from exc
        goal_spec_path = run_dir / "goal_spec.json"
        self.store.write(goal_spec_path, goal_spec, "goal_spec")
        event_logger.record(run["run_id"], "artifact_created", "GoalSpecAgent", "GoalSpec created")

        task_plan = RequirementPlanner().build_task_plan(goal_spec, runtime_context=runtime_context)
        for task in task_plan["tasks"]:
            self.validator.validate("task", task)
        task_plan_path = run_dir / "task_plan.json"
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        task_plan_eval = TaskPlanEvaluator().evaluate(
            task_plan,
            goal_spec,
            run_id=run["run_id"],
        )
        task_plan_eval_path = run_dir / "task_plan_eval.json"
        self.store.write(task_plan_eval_path, task_plan_eval, "task_plan_eval")
        event_logger.record(
            run["run_id"],
            "task_created",
            "PlannerAgent",
            f"Created {len(task_plan['tasks'])} tasks",
        )
        event_logger.record(
            run["run_id"],
            "verification_run",
            "TaskPlanEvaluator",
            task_plan_eval["summary"],
            {
                "status": task_plan_eval["status"],
                "overall_score": task_plan_eval["overall_score"],
                "issues": len(task_plan_eval["issues"]),
                "artifact": str(task_plan_eval_path),
            },
        )

        cost_report = budget.cost_report()
        cost_report_path = run_dir / "cost_report.json"
        self.store.write(cost_report_path, cost_report, "cost_report")

        run["goal_id"] = goal_spec["goal_id"]
        run["current_phase"] = "PLAN"
        run["status"] = "completed"
        run["summary"] = (
            f"Generated GoalSpec and {len(task_plan['tasks'])} tasks. "
            f"Task plan quality: {task_plan_eval['status']} "
            f"({task_plan_eval['overall_score']:.2f})."
        )
        run_store.update_run(run)
        run_store.set_current_session(run["run_id"], "plan_created")
        event_logger.record(run["run_id"], "run_completed", "PlanCommand", run["summary"])

        return PlanResult(
            run_id=run["run_id"],
            goal_spec_path=goal_spec_path,
            task_plan_path=task_plan_path,
            task_plan_eval_path=task_plan_eval_path,
            cost_report_path=cost_report_path,
            task_count=len(task_plan["tasks"]),
            task_plan_status=str(task_plan_eval["status"]),
            task_plan_score=float(task_plan_eval["overall_score"]),
        )
