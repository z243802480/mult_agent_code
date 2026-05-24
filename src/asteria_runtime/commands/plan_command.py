from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.core.run_config import apply_run_config, write_run_config
from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.models.model_failure import (
    ModelFailureRecorder,
    model_failure_context_from_client,
)
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.tools.defaults import create_default_tool_registry
from asteria_runtime.utils.time import now_iso


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
        *,
        mode: str = "plan",
        permission_level: str = "ask",
        model_strategy: str = "auto",
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.model_client = model_client
        self.mode = mode
        self.permission_level = permission_level
        self.model_strategy = model_strategy

    def run(self) -> PlanResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        policy = load_policy_config(agent_dir, self.validator)
        project_config = self.store.read(agent_dir / "project.json", "project_config")
        run_store = RunStore(agent_dir, self.validator)
        run = run_store.create_run(f'asteria plan "{self.goal}"')
        run_dir = run_store.run_dir(run["run_id"])
        run_config = write_run_config(
            run_dir=run_dir,
            validator=self.validator,
            run_id=run["run_id"],
            mode=self.mode,
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
        )
        policy = apply_run_config(policy, run_config)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        progress_logger = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
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
        progress_logger.record(
            run_id=run["run_id"],
            channel="conclusion",
            event_type="message",
            phase="understand",
            status="completed",
            title="理解目标",
            summary="Runtime accepted the user goal and started a planning run.",
            content_delta=self.goal,
        )
        event_logger.record(
            run["run_id"],
            "phase_changed",
            "PlanCommand",
            "INIT -> SPEC",
            {"from": "INIT", "to": "SPEC"},
        )
        runtime_context = ContextLoader(self.root, self.validator).load()
        prompt_envelope = persist_prompt_envelope(
            root=self.root,
            run_dir=run_dir,
            run_id=run["run_id"],
            mode="plan",
            policy=policy,
            validator=self.validator,
            tool_names=create_default_tool_registry().names(),
            event_logger=event_logger,
            progress_logger=progress_logger,
            phase="plan",
            actor="PlanCommand",
        )
        capability_manifest = prompt_envelope.envelope.capability_manifest
        runtime_context["capability_manifest"] = capability_manifest.to_dict()
        runtime_context["prompt_envelope"] = prompt_envelope.context_ref()
        goal_spec_route_plan = CapabilityFeedbackAdvisor(self.validator).goal_spec_execution_plan(
            agent_dir, self.goal
        )
        runtime_context["goal_spec_route_plan"] = goal_spec_route_plan
        event_logger.record(
            run["run_id"],
            "model_route_selected",
            "PlanCommand",
            "Selected GoalSpec model route.",
            goal_spec_route_plan,
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="model",
            event_type="start",
            phase="plan",
            status="running",
            title="制定计划",
            summary="Selecting a model route and generating a structured goal specification.",
            data={"model_route": goal_spec_route_plan},
            call_chain=["PlanCommand", "GoalSpecAgent"],
            execution_chain=["understand", "goal_spec"],
        )

        goal_spec_agent = GoalSpecAgent(model_client, self.validator)
        goal_spec_project_context = {
            "project": project_config,
            "runtime_context": runtime_context,
            "policy": {
                "decision_granularity": policy["decision_granularity"],
                "budgets": policy["budgets"],
                "permissions": policy["permissions"],
            },
            "capability_manifest": capability_manifest.to_dict(),
        }
        selected_model_tier = str(goal_spec_route_plan.get("selected_model_tier") or "strong")
        max_goal_spec_attempts = 2
        goal_spec = None
        last_exc: Exception | None = None
        last_report_path: Path | None = None
        last_report: dict | None = None
        for attempt in range(1, max_goal_spec_attempts + 1):
            try:
                goal_spec = goal_spec_agent.generate(
                    self.goal,
                    project_context=goal_spec_project_context,
                    run_id=run["run_id"],
                    model_tier=selected_model_tier,
                )
                if attempt > 1:
                    event_logger.record(
                        run["run_id"],
                        "model_route_retry_succeeded",
                        "GoalSpecAgent",
                        "GoalSpec model retry succeeded.",
                        {"attempt": attempt, "model_tier": selected_model_tier},
                    )
                break
            except Exception as exc:  # noqa: BLE001 - model boundary diagnostics
                last_exc = exc
                context = model_failure_context_from_client(
                    model_client,
                    model_tier=selected_model_tier,
                )
                last_report_path, last_report = ModelFailureRecorder(
                    self.root, self.validator
                ).record(
                    provider=context.provider,
                    model_name=context.model_name,
                    base_url=context.base_url,
                    error=exc,
                )
                retryable = bool(last_report.get("retryable"))
                if attempt < max_goal_spec_attempts and retryable:
                    event_logger.record(
                        run["run_id"],
                        "model_route_retry",
                        "GoalSpecAgent",
                        "Retrying GoalSpec model call after transient provider failure.",
                        {
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "model_tier": selected_model_tier,
                            "failure_type": last_report["failure_type"],
                            "failure_report": str(last_report_path),
                        },
                    )
                    continue
                break
        if goal_spec is None:
            report = last_report or {}
            report_path = (
                last_report_path or self.root / ".asteria" / "model" / "latest_failure.json"
            )
            failure_type = str(report.get("failure_type") or "unknown")
            run["current_phase"] = "SPEC"
            run["status"] = "failed"
            run["ended_at"] = now_iso()
            run["summary"] = (
                f"GoalSpec model call failed with {failure_type}. Failure report: {report_path}"
            )
            run_store.update_run(run)
            event_logger.record(
                run["run_id"],
                "run_failed",
                "GoalSpecAgent",
                run["summary"],
                {"failure_report": str(report_path), "failure_type": failure_type},
            )
            raise RuntimeError(run["summary"]) from last_exc
        goal_spec_path = run_dir / "goal_spec.json"
        self.store.write(goal_spec_path, goal_spec, "goal_spec")
        event_logger.record(run["run_id"], "artifact_created", "GoalSpecAgent", "GoalSpec created")
        progress_logger.record(
            run_id=run["run_id"],
            channel="file",
            event_type="file_created",
            phase="plan",
            status="completed",
            title="GoalSpec file written",
            summary="Persisted goal_spec.json for the planning run.",
            artifact_refs=[str(goal_spec_path)],
            evidence_refs=[str(goal_spec_path)],
            file_changes=[
                {
                    "path": str(goal_spec_path),
                    "operation": "created",
                    "event_type": "file_created",
                }
            ],
            call_chain=["PlanCommand", "GoalSpecAgent"],
            execution_chain=["understand", "goal_spec", "persist"],
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="evidence",
            event_type="evidence",
            phase="plan",
            status="running",
            title="目标规格已生成",
            summary="Goal specification artifact was created.",
            artifact_refs=[str(goal_spec_path)],
            evidence_refs=[str(goal_spec_path)],
            call_chain=["PlanCommand", "GoalSpecAgent"],
            execution_chain=["understand", "goal_spec"],
        )

        planner_event = progress_logger.record(
            run_id=run["run_id"],
            channel="tool",
            event_type="tool_call",
            phase="plan",
            status="running",
            title="Build task plan",
            summary="RequirementPlanner is converting the GoalSpec into a task graph.",
            display_level="inspector",
            call_chain=["PlanCommand", "RequirementPlanner"],
            execution_chain=["goal_spec", "task_plan"],
            data={"goal_id": goal_spec["goal_id"]},
        )
        task_plan = RequirementPlanner().build_task_plan(goal_spec, runtime_context=runtime_context)
        for task in task_plan["tasks"]:
            self.validator.validate("task", task)
        task_plan_path = run_dir / "task_plan.json"
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        progress_logger.record(
            run_id=run["run_id"],
            channel="tool",
            event_type="tool_output",
            phase="plan",
            status="completed",
            title="Task plan built",
            summary=f"Created {len(task_plan['tasks'])} task(s) from the GoalSpec.",
            display_level="inspector",
            parent_event_id=planner_event.get("event_id"),
            artifact_refs=[str(task_plan_path)],
            evidence_refs=[str(task_plan_path)],
            call_chain=["PlanCommand", "RequirementPlanner"],
            execution_chain=["goal_spec", "task_plan"],
            data={"task_count": len(task_plan["tasks"])},
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="file",
            event_type="file_created",
            phase="plan",
            status="completed",
            title="Task plan files written",
            summary="Persisted task_plan.json and refreshed the workspace backlog.",
            artifact_refs=[str(task_plan_path), str(agent_dir / "tasks" / "backlog.json")],
            evidence_refs=[str(task_plan_path)],
            file_changes=[
                {
                    "path": str(task_plan_path),
                    "operation": "created",
                    "event_type": "file_created",
                },
                {
                    "path": str(agent_dir / "tasks" / "backlog.json"),
                    "operation": "modified",
                    "event_type": "file_modified",
                },
            ],
            call_chain=["PlanCommand", "RequirementPlanner"],
            execution_chain=["goal_spec", "task_plan", "persist"],
        )
        evaluator_event = progress_logger.record(
            run_id=run["run_id"],
            channel="tool",
            event_type="tool_call",
            phase="review",
            status="running",
            title="Evaluate task plan",
            summary="TaskPlanEvaluator is checking plan quality before handoff.",
            display_level="inspector",
            call_chain=["PlanCommand", "TaskPlanEvaluator"],
            execution_chain=["task_plan", "task_plan_eval"],
            data={"task_count": len(task_plan["tasks"])},
        )
        task_plan_eval = TaskPlanEvaluator().evaluate(
            task_plan,
            goal_spec,
            run_id=run["run_id"],
        )
        task_plan_eval_path = run_dir / "task_plan_eval.json"
        self.store.write(task_plan_eval_path, task_plan_eval, "task_plan_eval")
        progress_logger.record(
            run_id=run["run_id"],
            channel="tool",
            event_type="tool_output",
            phase="review",
            status="completed",
            title="Task plan evaluated",
            summary=str(task_plan_eval["summary"]),
            display_level="inspector",
            parent_event_id=evaluator_event.get("event_id"),
            artifact_refs=[str(task_plan_eval_path)],
            evidence_refs=[str(task_plan_eval_path)],
            call_chain=["PlanCommand", "TaskPlanEvaluator"],
            execution_chain=["task_plan", "task_plan_eval"],
            data={
                "status": task_plan_eval["status"],
                "overall_score": task_plan_eval["overall_score"],
                "issues": len(task_plan_eval["issues"]),
            },
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="file",
            event_type="file_created",
            phase="review",
            status="completed",
            title="Task plan evaluation written",
            summary="Persisted task_plan_eval.json as planning evidence.",
            artifact_refs=[str(task_plan_eval_path)],
            evidence_refs=[str(task_plan_eval_path)],
            file_changes=[
                {
                    "path": str(task_plan_eval_path),
                    "operation": "created",
                    "event_type": "file_created",
                }
            ],
            call_chain=["PlanCommand", "TaskPlanEvaluator"],
            execution_chain=["task_plan", "task_plan_eval", "persist"],
        )
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
        progress_logger.record(
            run_id=run["run_id"],
            channel="evidence",
            event_type="evidence",
            phase="review",
            status="completed",
            title="计划质量核对",
            summary=str(task_plan_eval["summary"]),
            artifact_refs=[str(task_plan_eval_path)],
            evidence_refs=[str(task_plan_eval_path)],
            call_chain=["PlanCommand", "RequirementPlanner", "TaskPlanEvaluator"],
            execution_chain=["goal_spec", "task_plan", "task_plan_eval"],
            data={
                "status": task_plan_eval["status"],
                "overall_score": task_plan_eval["overall_score"],
                "issues": len(task_plan_eval["issues"]),
            },
        )

        cost_report = budget.cost_report()
        cost_report_path = run_dir / "cost_report.json"
        self.store.write(cost_report_path, cost_report, "cost_report")
        progress_logger.record(
            run_id=run["run_id"],
            channel="file",
            event_type="file_created",
            phase="review",
            status="completed",
            title="Cost report written",
            summary="Persisted cost_report.json for budget and routing evidence.",
            artifact_refs=[str(cost_report_path)],
            evidence_refs=[str(cost_report_path)],
            file_changes=[
                {
                    "path": str(cost_report_path),
                    "operation": "created",
                    "event_type": "file_created",
                }
            ],
            call_chain=["PlanCommand", "BudgetController"],
            execution_chain=["task_plan_eval", "cost_report", "persist"],
        )

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
        progress_logger.record(
            run_id=run["run_id"],
            channel="conclusion",
            event_type="message",
            phase="result",
            status="completed",
            title="计划已生成",
            summary=run["summary"],
            artifact_refs=[
                str(goal_spec_path),
                str(task_plan_path),
                str(task_plan_eval_path),
                str(cost_report_path),
            ],
            evidence_refs=[
                str(goal_spec_path),
                str(task_plan_path),
                str(task_plan_eval_path),
                str(cost_report_path),
            ],
            call_chain=["PlanCommand", "GoalSpecAgent", "RequirementPlanner", "TaskPlanEvaluator"],
            execution_chain=["understand", "goal_spec", "task_plan", "task_plan_eval", "result"],
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="conclusion",
            event_type="message",
            phase="next",
            status="completed",
            title="下一步",
            summary="Review the plan, then run it with bounded permissions or adjust scope.",
            content_delta="You can continue with `asteria run --root <workspace>` or ask Studio to execute the plan after confirming permissions.",
        )

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
