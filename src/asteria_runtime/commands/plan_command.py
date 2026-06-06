from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.agent_loop_profiles import AgentLoopProfileRegistry
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.design_intel_contract import (
    apply_research_type_to_goal_spec,
    apply_research_type_to_task_plan,
)
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.core.execution_profile import resolve_execution_profile
from asteria_runtime.core.fast_path_policy import classify_fast_path
from asteria_runtime.core.run_config import apply_run_config, write_run_config
from asteria_runtime.core.workspace_registry import WorkspaceRegistry
from asteria_runtime.core.user_progress_view import build_plan_completion_copy
from asteria_runtime.core.workspace_envelope import (
    build_workspace_envelope,
    workspace_summary,
    write_workspace_envelope,
)
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
    output_root: Path
    artifact_root: Path
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
                f"Output root: {self.output_root}",
                f"Artifact root: {self.artifact_root}",
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
        global_config_dir: Path | None = None,
        input_roots: list[Path] | None = None,
        output_root: Path | None = None,
        artifact_root: Path | None = None,
        worktree_policy: str = "controlled_patch",
        validation_probe_ids: list[str] | None = None,
        force_harness: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.model_client = model_client
        self.mode = mode
        self.permission_level = permission_level
        self.model_strategy = model_strategy
        self.global_config_dir = global_config_dir
        self.input_roots = input_roots
        self.output_root = output_root
        self.artifact_root = artifact_root
        self.worktree_policy = worktree_policy
        self.validation_probe_ids = list(validation_probe_ids or [])
        self.force_harness = force_harness

    def run(self) -> PlanResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        policy = load_policy_config(agent_dir, self.validator)
        project_config = self.store.read(agent_dir / "project.json", "project_config")
        run_store = RunStore(agent_dir, self.validator)
        run = run_store.create_run(f'asteria plan "{self.goal}"')
        run_dir = run_store.run_dir(run["run_id"])
        workspace_envelope = build_workspace_envelope(
            workspace_root=self.root,
            permission_level=self.permission_level,
            input_roots=self.input_roots,
            output_root=self.output_root,
            artifact_root=self.artifact_root,
            candidate_workspace_policy=self.worktree_policy,
            worktree_policy=self.worktree_policy,
        )
        try:
            WorkspaceRegistry(self.global_config_dir, self.validator).record_workspace(
                workspace_root=self.root,
                name=str(project_config.get("name") or self.root.name),
                output_root=Path(str(workspace_envelope["output_root"])),
                artifact_root=Path(str(workspace_envelope["artifact_root"])),
            )
        except OSError:
            pass
        write_workspace_envelope(
            run_dir=run_dir,
            validator=self.validator,
            envelope=workspace_envelope,
        )
        run["workspace"] = workspace_summary(workspace_envelope)
        run_store.update_run(run)
        profile_resolution = resolve_execution_profile(
            self.goal,
            parallel_writes=self.worktree_policy == "disjoint_parallel",
            force_harness=self.force_harness,
        )
        fast_path = classify_fast_path(self.goal)
        run_config = write_run_config(
            run_dir=run_dir,
            validator=self.validator,
            run_id=run["run_id"],
            mode=self.mode,
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
            workspace_envelope=workspace_envelope,
            execution_profile=profile_resolution.to_dict(),
            fast_path=fast_path.to_dict(),
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
            channel="progress",
            event_type="start",
            phase="plan",
            status="running",
            title="制定计划",
            summary="正在把目标拆成可执行步骤。",
            data={"model_route": goal_spec_route_plan},
            call_chain=["PlanCommand", "GoalSpecAgent"],
            execution_chain=["understand", "goal_spec"],
            display_level="main",
            transcript_kind="plan",
            ui_intent="work_progress",
        )
        progress_logger.workspace_event(
            run_id=run["run_id"],
            title="Workspace selected",
            summary="Runtime bound this plan to the selected workspace and output scope.",
            workspace=workspace_envelope,
            output_locations={
                "workspace_root": workspace_envelope["workspace_root"],
                "input_roots": workspace_envelope["input_roots"],
                "output_root": workspace_envelope["output_root"],
                "artifact_root": workspace_envelope["artifact_root"],
                "worktree_policy": workspace_envelope["worktree_policy"],
            },
            phase="plan",
        )
        progress_logger.permission_event(
            run_id=run["run_id"],
            title="Permission mode selected",
            summary=f"Permission mode is {run_config['permission_mode']}.",
            permission=run_config["permission_policy"],
            phase="plan",
        )

        goal_spec_agent = GoalSpecAgent(model_client, self.validator)
        goal_spec_project_context = {
            "project": project_config,
            "runtime_context": runtime_context,
            "policy": {
                "decision_granularity": policy["decision_granularity"],
                "budgets": policy["budgets"],
                "permissions": policy["permissions"],
                "provider_route_strategy": policy.get("provider_route_strategy", {}),
                "runtime_deadlines": policy.get("runtime_deadlines", {}),
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
        if goal_spec is None and self.validation_probe_ids:
            report = last_report or {}
            report_path = (
                last_report_path or self.root / ".asteria" / "model" / "latest_failure.json"
            )
            failure_type = str(report.get("failure_type") or "unknown")
            goal_spec = _validation_probe_goal_spec(self.goal, self.validation_probe_ids)
            event_logger.record(
                run["run_id"],
                "goal_spec_fallback",
                "PlanCommand",
                "Used deterministic GoalSpec fallback for targeted validation probe.",
                {
                    "validation_probe_ids": self.validation_probe_ids,
                    "failure_report": str(report_path),
                    "failure_type": failure_type,
                },
            )
            progress_logger.record(
                run_id=run["run_id"],
                channel="model",
                event_type="message",
                phase="plan",
                status="completed",
                title="Validation GoalSpec fallback used",
                summary=(
                    "Provider GoalSpec generation failed, so targeted validation probe "
                    "planning used a deterministic schema-valid GoalSpec."
                ),
                display_level="inspector",
                transcript_kind="diagnostic",
                data={
                    "validation_probe_ids": self.validation_probe_ids,
                    "failure_report": str(report_path),
                    "failure_type": failure_type,
                },
                call_chain=["PlanCommand", "GoalSpecAgent"],
                execution_chain=["understand", "goal_spec", "fallback"],
            )
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
        goal_spec = apply_research_type_to_goal_spec(goal_spec)
        design_intel_research_type = goal_spec.get("research_type")
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
            data={
                "goal_id": goal_spec["goal_id"],
                **(
                    {"research_type": design_intel_research_type}
                    if design_intel_research_type
                    else {}
                ),
            },
        )
        task_plan = RequirementPlanner().build_task_plan(
            goal_spec,
            runtime_context=runtime_context,
            execution_profile=profile_resolution.profile_id,
        )
        task_plan = apply_research_type_to_task_plan(goal_spec, task_plan)
        _apply_validation_probe_hints(task_plan, self.validation_probe_ids)
        for task in task_plan["tasks"]:
            self.validator.validate("task", task)
        loop_dispatch = AgentLoopProfileRegistry().dispatch_plan(
            task_plan["tasks"],
            permission_mode=str(run_config["permission_mode"]),
        )
        for task_dispatch in loop_dispatch["task_dispatch"]:
            for task in task_plan["tasks"]:
                if task.get("task_id") != task_dispatch.get("task_id"):
                    continue
                task["agent_loop_profile"] = {
                    "loop_profile_id": task_dispatch["loop_profile_id"],
                    "parallelism": task_dispatch["parallelism"],
                    "capability_groups": task_dispatch["capability_groups"],
                    "output_contract": task_dispatch["output_contract"],
                    "validation_contract": task_dispatch["validation_contract"],
                    "failure_recovery": task_dispatch["failure_recovery"],
                    "decision_escalation": task_dispatch["decision_escalation"],
                    "dispatch_reason": task_dispatch["dispatch_reason"],
                }
                break
        task_plan_path = run_dir / "task_plan.json"
        loop_dispatch_path = run_dir / "agent_loop_dispatch.json"
        self.store.write(task_plan_path, task_plan, "task_board")
        loop_dispatch_path.write_text(
            json.dumps(loop_dispatch, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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
            artifact_refs=[str(task_plan_path), str(loop_dispatch_path)],
            evidence_refs=[str(task_plan_path), str(loop_dispatch_path)],
            call_chain=["PlanCommand", "RequirementPlanner"],
            execution_chain=["goal_spec", "task_plan"],
            data={
                "task_count": len(task_plan["tasks"]),
                "agent_loop_dispatch": loop_dispatch,
                **(
                    {"research_type": design_intel_research_type}
                    if design_intel_research_type
                    else {}
                ),
            },
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="evidence",
            event_type="evidence",
            phase="plan",
            status="completed",
            title="Agent loop profiles selected",
            summary=(
                "Runtime selected loop profiles for planned tasks: "
                f"{loop_dispatch['profile_counts']}."
            ),
            display_level="inspector",
            artifact_refs=[str(loop_dispatch_path)],
            evidence_refs=[str(loop_dispatch_path)],
            call_chain=["PlanCommand", "AgentLoopProfileRegistry"],
            execution_chain=["goal_spec", "task_plan", "agent_loop_dispatch"],
            data={"agent_loop_dispatch": loop_dispatch},
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="file",
            event_type="file_created",
            phase="plan",
            status="completed",
            title="Task plan files written",
            summary="Persisted task_plan.json and refreshed the workspace backlog.",
            artifact_refs=[
                str(task_plan_path),
                str(loop_dispatch_path),
                str(agent_dir / "tasks" / "backlog.json"),
            ],
            evidence_refs=[str(task_plan_path), str(loop_dispatch_path)],
            file_changes=[
                {
                    "path": str(task_plan_path),
                    "operation": "created",
                    "event_type": "file_created",
                },
                {
                    "path": str(loop_dispatch_path),
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
        task_titles = [
            str(task.get("title") or task.get("description") or "").strip()
            for task in task_plan.get("tasks") or []
        ]
        plan_title, plan_summary = build_plan_completion_copy(
            task_count=len(task_plan["tasks"]),
            task_titles=task_titles,
            quality_status=str(task_plan_eval["status"]),
            quality_score=float(task_plan_eval["overall_score"]),
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="progress",
            event_type="message",
            phase="plan",
            status="completed",
            title=plan_title,
            summary=plan_summary,
            display_level="main",
            transcript_kind="plan",
            ui_intent="work_progress",
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
            execution_chain=["understand", "goal_spec", "task_plan", "task_plan_eval", "plan"],
            data={
                "task_count": len(task_plan["tasks"]),
                "task_titles": task_titles[:5],
                "quality_status": task_plan_eval["status"],
                "quality_score": task_plan_eval["overall_score"],
                **(
                    {"research_type": design_intel_research_type}
                    if design_intel_research_type
                    else {}
                ),
            },
        )
        progress_logger.record(
            run_id=run["run_id"],
            channel="progress",
            event_type="message",
            phase="next",
            status="completed",
            title="下一步",
            summary="请查看计划，确认权限后执行或调整范围。",
            content_delta="可继续 `asteria run --root <workspace>`，或在 Studio 确认权限后执行计划。",
            display_level="main",
            transcript_kind="progress",
            ui_intent="inform",
        )

        return PlanResult(
            run_id=run["run_id"],
            goal_spec_path=goal_spec_path,
            task_plan_path=task_plan_path,
            task_plan_eval_path=task_plan_eval_path,
            cost_report_path=cost_report_path,
            output_root=Path(str(workspace_envelope["output_root"])),
            artifact_root=Path(str(workspace_envelope["artifact_root"])),
            task_count=len(task_plan["tasks"]),
            task_plan_status=str(task_plan_eval["status"]),
            task_plan_score=float(task_plan_eval["overall_score"]),
        )


def _apply_validation_probe_hints(task_plan: dict, probe_ids: list[str]) -> None:
    selected = [str(item) for item in probe_ids if str(item)]
    if not selected:
        return
    tasks = [item for item in task_plan.get("tasks") or [] if isinstance(item, dict)]
    if not tasks:
        return
    task = tasks[0]
    task_plan["tasks"] = [task]
    hints = dict(task.get("runtime_profile_hints") or {})
    hints["validation_probe_ids"] = selected
    hints["runtime_managed_validation_probe"] = True
    if any(
        probe_id
        in {
            "parent_selects_subagent",
            "readonly_fanout_succeeds",
            "readonly_write_tool_blocked",
            "disjoint_write_gate_blocks_unsafe_fanout",
        }
        for probe_id in selected
    ):
        hints["force_next_action"] = "subagent"
    task["runtime_profile_hints"] = hints
    if any(
        probe_id in {"readonly_fanout_succeeds", "readonly_write_tool_blocked"}
        for probe_id in selected
    ):
        _apply_readonly_fanout_probe_hint(task, selected)
    if "disjoint_write_gate_blocks_unsafe_fanout" in selected:
        _apply_disjoint_write_probe_hint(task)
    if "repair_replan_path" in selected:
        _apply_repair_replan_probe_hint(task)
    if "ask_stop_path" in selected:
        _apply_ask_stop_probe_hint(task)
    if "context_pressure_path" in selected:
        _apply_context_pressure_probe_hint(task)
    if "capability_selection_path" in selected:
        _apply_capability_selection_probe_hint(task)


def _validation_probe_goal_spec(goal: str, probe_ids: list[str]) -> dict:
    selected = [str(item) for item in probe_ids if str(item)]
    probe_list = ", ".join(selected) or "unknown"
    return {
        "schema_version": "0.1.0",
        "goal_id": "goal-validation-probe",
        "original_goal": goal,
        "normalized_goal": goal,
        "goal_type": "report",
        "assumptions": [
            "A targeted validation probe may use deterministic GoalSpec fallback when provider GoalSpec generation fails."
        ],
        "constraints": [
            "Fallback is only active when validation_probe_ids are present.",
            "Do not use tiny file artifacts as the primary proof for this validation path.",
        ],
        "non_goals": [
            "Do not widen ordinary runtime planning fallback.",
            "Do not bypass validation-run probe evaluation.",
        ],
        "expanded_requirements": [
            {
                "id": "req-validation-probe-0001",
                "priority": "must",
                "description": f"Run targeted validation probe(s): {probe_list}.",
                "source": "user",
                "acceptance": [
                    "Runtime records the targeted validation evidence required by validation-run.",
                    "Validation probe result is evaluated from durable runtime evidence.",
                ],
            }
        ],
        "target_outputs": ["runtime evidence"],
        "definition_of_done": [
            "Targeted validation probe evidence is present in .asteria run evidence."
        ],
        "verification_strategy": ["Run validation-run probe evaluator."],
        "budget": {"max_iterations": 3, "max_repair_attempts": 1},
    }


def _apply_readonly_fanout_probe_hint(task: dict, probe_ids: list[str]) -> None:
    task["task_kind"] = "research"
    task["parallel_safety"] = "readonly"
    task["read_scope"] = [".asteria/project.json"]
    if "readonly_write_tool_blocked" in set(probe_ids):
        task["read_scope"] = [
            ".asteria/project.json",
            "readonly_write_gate_probe.txt",
        ]
    task["write_scope"] = []
    task["expected_changed_files"] = []
    task["expected_artifacts"] = []
    task["allowed_tools"] = ["list_files", "read_file", "search_text", "run_command"]
    task["acceptance"] = [
        "inspect validation probe path alpha without writing files",
        "inspect validation probe path beta without writing files",
    ]
    task["completion_contract"] = {
        "requires_changed_artifact": False,
        "requires_verification": True,
        "allows_expected_failure": False,
    }
    task["verification_policy"] = {
        "required": True,
        "allow_expected_failure": False,
        "commands": [],
    }
    task["multi_agent_strategy"] = {
        "mode": "readonly_fanout",
        "max_child_workers": 2,
        "planner_child_plan": True,
        "coordination_policy": {
            "write_allowed": False,
            "requires_merge_gate": False,
            "requires_summary": True,
            "scale_out_limit": 2,
        },
        "reason": "validation probe requires readonly child fanout evidence",
    }


def _apply_disjoint_write_probe_hint(task: dict) -> None:
    task["parallel_safety"] = "disjoint_writes"
    task["write_scope"] = ["validation-probe-a.txt", "validation-probe-b.txt"]
    task["expected_changed_files"] = list(task["write_scope"])
    task["allowed_tools"] = ["write_file", "run_command"]
    task["multi_agent_strategy"] = {
        "mode": "disjoint_write_workers",
        "max_child_workers": 2,
        "planner_child_plan": True,
        "coordination_policy": {
            "write_allowed": True,
            "requires_merge_gate": True,
            "requires_disjoint_write_scope": True,
            "scale_out_limit": 2,
        },
        "reason": "validation probe must prove unsafe disjoint write fanout is blocked",
    }


def _apply_repair_replan_probe_hint(task: dict) -> None:
    task["task_kind"] = "diagnostic"
    task["parallel_safety"] = "serial"
    task["read_scope"] = ["AGENTS.md", "benchmarks/failing_tests_project"]
    task["write_scope"] = []
    task["expected_changed_files"] = []
    task["expected_artifacts"] = []
    task["allowed_tools"] = ["run_command"]
    task["acceptance"] = [
        "runtime records a failed tool observation",
        "runtime records a repair or replan AgentLoopDecision",
        "runtime records repair/replan dispatch evidence",
    ]
    task["completion_contract"] = {
        "requires_changed_artifact": False,
        "requires_verification": True,
        "allows_expected_failure": False,
    }
    task["verification_policy"] = {
        "required": True,
        "allow_expected_failure": False,
        "commands": [],
    }
    task["context_requirements"] = {
        "mount_type": "debug_context",
        "include_artifacts": False,
        "include_failures": True,
        "include_decisions": True,
        "include_validation": True,
        "recent_event_count": 10,
    }
    task.pop("multi_agent_strategy", None)


def _apply_ask_stop_probe_hint(task: dict) -> None:
    task["task_kind"] = "diagnostic"
    task["parallel_safety"] = "serial"
    task["read_scope"] = ["AGENTS.md"]
    task["write_scope"] = []
    task["expected_changed_files"] = []
    task["expected_artifacts"] = []
    task["allowed_tools"] = ["list_files", "read_file", "search_text"]
    task["acceptance"] = [
        "runtime records a DecisionPoint for ambiguous or policy-sensitive work",
        "runtime stops instead of guessing past the boundary",
    ]
    task["completion_contract"] = {
        "requires_changed_artifact": False,
        "requires_verification": False,
        "allows_expected_failure": True,
    }
    task["verification_policy"] = {
        "required": False,
        "allow_expected_failure": True,
        "commands": [],
    }
    task["context_requirements"] = {
        "mount_type": "debug_context",
        "include_artifacts": False,
        "include_failures": True,
        "include_decisions": True,
        "include_validation": True,
        "recent_event_count": 10,
    }
    task.pop("multi_agent_strategy", None)


def _apply_context_pressure_probe_hint(task: dict) -> None:
    task["task_kind"] = "diagnostic"
    task["parallel_safety"] = "serial"
    task["read_scope"] = ["AGENTS.md", "docs/zh/当前状态与路线.md"]
    task["write_scope"] = []
    task["expected_changed_files"] = []
    task["expected_artifacts"] = []
    task["allowed_tools"] = ["read_file", "search_text"]
    task["acceptance"] = [
        "runtime records a context budget snapshot with compact boundary required",
        "runtime stops after making context pressure visible to validation",
    ]
    task["completion_contract"] = {
        "requires_changed_artifact": False,
        "requires_verification": False,
        "allows_expected_failure": True,
    }
    task["verification_policy"] = {
        "required": False,
        "allow_expected_failure": True,
        "commands": [],
    }
    task["context_requirements"] = {
        "mount_type": "debug_context",
        "include_artifacts": False,
        "include_failures": True,
        "include_decisions": True,
        "include_validation": True,
        "recent_event_count": 40,
    }
    task.pop("multi_agent_strategy", None)


def _apply_capability_selection_probe_hint(task: dict) -> None:
    task["task_kind"] = "diagnostic"
    task["risk"] = "medium"
    task["parallel_safety"] = "serial"
    task["read_scope"] = ["AGENTS.md", "docs/zh/运行命令.md"]
    task["write_scope"] = []
    task["expected_changed_files"] = []
    task["expected_artifacts"] = []
    task["allowed_tools"] = ["read_file", "search_text"]
    task["allowed_mcp"] = ["runtime_matrix/echo"]
    task["mcp_servers"] = [{"name": "runtime_matrix", "tools": ["echo"]}]
    task["acceptance"] = [
        "runtime records a reasoned capability decision",
        "runtime records adapter invocation evidence with decision reason",
        "runtime records a capability progress event",
    ]
    task["completion_contract"] = {
        "requires_changed_artifact": False,
        "requires_verification": False,
        "allows_expected_failure": True,
    }
    task["verification_policy"] = {
        "required": False,
        "allow_expected_failure": True,
        "commands": [],
    }
    task["context_requirements"] = {
        "mount_type": "debug_context",
        "include_artifacts": False,
        "include_failures": True,
        "include_decisions": True,
        "include_validation": True,
        "recent_event_count": 20,
    }
    task.pop("multi_agent_strategy", None)
