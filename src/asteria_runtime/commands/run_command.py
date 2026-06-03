from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.compact_command import CompactCommand
from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.commands.research_command import ResearchCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.commands.status_command import StatusCommand, StatusResult
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.active_next_step import capability_feedback_active_next_step
from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.agent_loop_profiles import AgentLoopProfileRegistry
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.agent_harness import recommended_route_from_observation_plan
from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.main_path import (
    build_main_path,
    canonical_next_command,
    main_path_text_lines,
)
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.permission_policy import normalize_permission_mode
from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.core.runtime_progress import build_runtime_progress
from asteria_runtime.core.todo_view import build_todo_view, todo_view_text_lines
from asteria_runtime.models.base import ModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class RunStepSummary:
    name: str
    status: str
    summary: str


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    final_report_path: Path
    final_report_summary_path: Path | None = None
    final_report_summary: dict = field(default_factory=dict)
    steps: list[RunStepSummary] = field(default_factory=list)
    run_loop_summary_path: Path | None = None
    workflow_state: str | None = None
    current_phase: str | None = None
    current_blocker: str | None = None
    recommended_next_command: str | None = None
    next_actions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            f"Run: {self.run_id}",
            f"Status: {self.status}",
            f"Final report: {self.final_report_path}",
        ]
        if self.final_report_summary_path:
            lines.append(f"Final report summary: {self.final_report_summary_path}")
        if self.run_loop_summary_path:
            lines.append(f"Run loop summary: {self.run_loop_summary_path}")
        if self.workflow_state:
            lines.append(f"Workflow: {self.workflow_state}")
        if self.current_phase:
            lines.append(f"Current phase: {self.current_phase}")
        if self.current_blocker:
            lines.append(f"Current blocker: {self.current_blocker}")
        if self.recommended_next_command:
            lines.append(f"Recommended next command: asteria {self.recommended_next_command}")
        elif self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {action}" for action in self.next_actions)
        if self.steps:
            lines.append("Loop steps:")
        for step in self.steps:
            lines.append(f"- {step.name}: {step.status} - {step.summary}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "status": self.status,
            "final_report_path": str(self.final_report_path),
            "final_report_summary_path": (
                str(self.final_report_summary_path) if self.final_report_summary_path else None
            ),
            "final_report_summary": self.final_report_summary,
            "run_loop_summary_path": (
                str(self.run_loop_summary_path) if self.run_loop_summary_path else None
            ),
            "workflow_state": self.workflow_state,
            "current_phase": self.current_phase,
            "current_blocker": self.current_blocker,
            "recommended_next_command": self.recommended_next_command,
            "next_actions": self.next_actions,
            "steps": [
                {"name": step.name, "status": step.status, "summary": step.summary}
                for step in self.steps
            ],
        }


class RunCommand:
    def __init__(
        self,
        root: Path,
        goal: str | None = None,
        run_id: str | None = None,
        max_iterations: int | None = None,
        max_tasks_per_iteration: int = 1,
        model_client: ModelClient | None = None,
        plan_model_client: ModelClient | None = None,
        execute_model_client: ModelClient | None = None,
        debug_model_client: ModelClient | None = None,
        review_model_client: ModelClient | None = None,
        research_model_client: ModelClient | None = None,
        enable_research: bool = True,
        parallel_writes: bool = False,
        mode: str = "goal",
        permission_level: str = "balanced",
        model_strategy: str = "auto",
        input_roots: list[Path] | None = None,
        output_root: Path | None = None,
        artifact_root: Path | None = None,
        worktree_policy: str = "controlled_patch",
        validation_probe_ids: list[str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.run_id = run_id
        self.max_iterations = max_iterations
        self.max_tasks_per_iteration = max_tasks_per_iteration
        self.model_client = model_client
        self.plan_model_client = plan_model_client
        self.execute_model_client = execute_model_client
        self.debug_model_client = debug_model_client
        self.review_model_client = review_model_client
        self.research_model_client = research_model_client
        self.enable_research = enable_research
        self.parallel_writes = parallel_writes
        self.mode = mode
        self.permission_level = permission_level
        self.model_strategy = model_strategy
        self.input_roots = input_roots
        self.output_root = output_root
        self.artifact_root = artifact_root
        self.worktree_policy = worktree_policy
        self.validation_probe_ids = list(validation_probe_ids or [])
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> RunResult:
        if not (self.root / ".asteria").exists():
            InitCommand(self.root).run()
        if self.goal and self.run_id:
            raise ValueError("Pass either a new goal or an existing session id, not both.")
        if not self.goal:
            run_store = RunStore(self.root / ".asteria", self.validator)
            run_id = self.run_id or run_store.current_session_id()
            if not run_id:
                raise RuntimeError('No current session found. Run `asteria new "goal"` first.')
            return self.continue_run(run_id)

        steps: list[RunStepSummary] = []
        research_context = ""
        if self.enable_research:
            try:
                research = ResearchCommand(
                    self.root,
                    self.goal,
                    model_client=self.research_model_client or self.model_client,
                ).run()
                research_context = self._research_context(research.report_path)
                steps.append(
                    RunStepSummary(
                        "research",
                        "completed",
                        f"{research.source_count} sources, {research.claim_count} claims.",
                    )
                )
            # Research can improve planning, but a local run should still proceed without sources.
            except Exception as exc:  # noqa: BLE001
                steps.append(RunStepSummary("research", "skipped", str(exc)))

        if research_context:
            plan_goal = f"{self.goal}\n\nResearch context:\n{research_context}"
        else:
            plan_goal = self.goal
        plan = PlanCommand(
            self.root,
            plan_goal,
            model_client=self.plan_model_client or self.model_client,
            mode=self.mode,
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
            input_roots=self.input_roots,
            output_root=self.output_root,
            artifact_root=self.artifact_root,
            worktree_policy=self.worktree_policy,
            validation_probe_ids=self.validation_probe_ids,
        ).run()
        steps.append(RunStepSummary("plan", "completed", f"Created {plan.task_count} task(s)."))

        # Emit a progress event so Studio knows planning finished and execution starts
        run_dir = self.root / ".asteria" / "runs" / plan.run_id
        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
        progress.record(
            run_id=plan.run_id,
            channel="progress",
            phase="execute",
            status="running",
            title="计划完成，开始执行",
            summary=f"已生成 {plan.task_count} 个任务，正在启动执行阶段。",
            display_level="main",
        )
        return self.continue_run(plan.run_id, steps, _progress=progress)

    def continue_run(
        self,
        run_id: str,
        steps: list[RunStepSummary] | None = None,
        _progress: UserProgressLogger | None = None,
    ) -> RunResult:
        steps = steps or []
        # Create a progress logger if caller didn't supply one (e.g. resume path)
        if _progress is None:
            run_dir = self.root / ".asteria" / "runs" / run_id
            _progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
            _progress.record(
                run_id=run_id,
                channel="progress",
                phase="execute",
                status="running",
                title="恢复执行",
                summary="正在检查任务状态，准备继续推进。",
                display_level="main",
            )
        self._emit_workspace_progress_event(_progress, run_id, phase="execute")
        self._emit_agent_loop_dispatch(_progress, run_id, phase="execute")

        if self._ready_count(run_id) > 0 and self._task_plan_quality_gate(run_id, steps):
            compact = CompactCommand(self.root, run_id=run_id, focus="task plan quality gate").run()
            steps.append(
                RunStepSummary("compact", "completed", f"Snapshot: {compact.snapshot_path.name}.")
            )
            review_status = self._latest_review_status(run_id)
            final_report_path = self._write_final_report(
                run_id,
                review_status,
                steps,
            )
            self._write_final_report_summary(
                run_id=run_id,
                status=self._run_status(run_id),
                review_status=review_status,
                final_report_path=final_report_path,
                status_payload=self._status_payload(run_id),
            )
            run_loop_summary_path = self._write_run_loop_summary(
                run_id=run_id,
                steps=steps,
                status_payload=self._status_payload(run_id),
                stop_reason=self._stop_reason(steps, max_iterations=0),
            )
            self._emit_execution_progress_events(_progress, run_id, phase="review")
            self._emit_final_report_progress_event(
                _progress,
                run_id=run_id,
                final_report_path=final_report_path,
                final_report_summary_path=final_report_path.with_name("final_report_summary.json"),
            )
            return self._build_run_result(
                run_id=run_id,
                status=self._run_status(run_id),
                final_report_path=final_report_path,
                steps=steps,
                run_loop_summary_path=run_loop_summary_path,
            )
        max_iterations = (
            self.max_iterations if self.max_iterations is not None else self._policy_iterations()
        )
        for index in range(max_iterations):
            if self._budget_guard(run_id, steps, f"iteration-{index + 1}-execute"):
                break
            _progress.record(
                run_id=run_id,
                channel="progress",
                phase="execute",
                status="running",
                title=f"执行迭代 {index + 1}",
                summary=f"正在执行第 {index + 1} 轮任务，最多处理 {self.max_tasks_per_iteration} 个任务。",
                display_level="main",
            )
            self._execute_until_no_ready(run_id, steps, iteration=index + 1, progress=_progress)
            self._emit_execution_progress_events(_progress, run_id, phase="execute")
            if self._runtime_managed_validation_probe_has_evidence(run_id):
                steps.append(
                    RunStepSummary(
                        "validation-probe",
                        "evidence_recorded",
                        "Runtime-managed validation probe evidence was recorded; skipping ordinary debug/review loop.",
                    )
                )
                return self._finalize_validation_probe_run(run_id, steps, _progress)
            if self._run_status(run_id) in {"blocked", "paused"}:
                break

            if self._budget_guard(run_id, steps, f"iteration-{index + 1}-review"):
                break
            _progress.record(
                run_id=run_id,
                channel="progress",
                phase="review",
                status="running",
                title="评审阶段",
                summary="正在评审本轮执行结果，判断是否需要修复或继续。",
                display_level="main",
            )
            review = ReviewCommand(
                self.root,
                run_id=run_id,
                model_client=self.review_model_client,
            ).run()
            steps.append(
                RunStepSummary(
                    "review",
                    review.status,
                    (
                        f"Score {review.score:.2f}; "
                        f"{review.follow_up_count} follow-up task(s); "
                        f"{review.decision_count} decision point(s)."
                    ),
                )
            )
            _progress.record(
                run_id=run_id,
                channel="progress",
                phase="review",
                status="running" if review.follow_up_count > 0 else "completed",
                title="评审完成",
                summary=(
                    f"评分 {review.score:.2f}；"
                    f"{review.follow_up_count} 个后续任务；"
                    f"{review.decision_count} 个待决策点。"
                ),
                display_level="main",
            )
            self._emit_execution_progress_events(_progress, run_id, phase="review")
            goal_decision = self._goal_loop_decision(
                run_id=run_id,
                review_status=review.status,
                follow_up_count=review.follow_up_count,
                decision_count=review.decision_count,
                iteration=index + 1,
                max_iterations=max_iterations,
            )
            steps.append(
                RunStepSummary(
                    "goal-policy",
                    str(goal_decision["action"]),
                    str(goal_decision["reason"]),
                )
            )
            if goal_decision["action"] == "auto_accept":
                from asteria_runtime.commands.accept_command import AcceptCommand

                accept = AcceptCommand(
                    self.root,
                    run_id=run_id,
                    skip_review=True,
                    promote_all=False,
                ).run()
                steps.append(
                    RunStepSummary(
                        "accept",
                        "accepted" if accept.accepted else "blocked",
                        accept.primary_blocker or "Accepted automatically by goal loop policy.",
                    )
                )
                break
            if goal_decision["action"] in {
                "stop_for_decision",
                "stop_for_accept",
                "stop_for_repair",
            }:
                break
            if index == max_iterations - 1:
                break

        compact = CompactCommand(self.root, run_id=run_id, focus="final run handoff").run()
        steps.append(
            RunStepSummary("compact", "completed", f"Snapshot: {compact.snapshot_path.name}.")
        )

        review_status = self._latest_review_status(run_id)
        final_report_path = self._write_final_report(run_id, review_status, steps)
        run_status = self._run_status(run_id)
        _progress.conclusion(
            run_id=run_id,
            phase="result",
            title="运行完成" if run_status == "completed" else "运行结束",
            summary=(f"Run {run_id} 已完成，状态：{run_status}。共 {len(steps)} 个执行步骤。"),
            artifact_refs=[str(final_report_path)],
        )
        status_payload = self._status_payload(run_id)
        final_report_summary_path = self._write_final_report_summary(
            run_id=run_id,
            status=run_status,
            review_status=review_status,
            final_report_path=final_report_path,
            status_payload=status_payload,
        )
        run_loop_summary_path = self._write_run_loop_summary(
            run_id=run_id,
            steps=steps,
            status_payload=status_payload,
            stop_reason=self._stop_reason(steps, max_iterations=max_iterations),
        )
        self._emit_execution_progress_events(_progress, run_id, phase="review")
        self._emit_final_report_progress_event(
            _progress,
            run_id=run_id,
            final_report_path=final_report_path,
            final_report_summary_path=final_report_summary_path,
        )
        return self._build_run_result(
            run_id=run_id,
            status=run_status,
            final_report_path=final_report_path,
            steps=steps,
            status_payload=status_payload,
            run_loop_summary_path=run_loop_summary_path,
        )

    def _finalize_validation_probe_run(
        self,
        run_id: str,
        steps: list[RunStepSummary],
        progress: UserProgressLogger,
    ) -> RunResult:
        review_status = self._latest_review_status(run_id)
        final_report_path = self._write_final_report(run_id, review_status, steps)
        run_status = self._run_status(run_id)
        status_payload = self._status_payload(run_id)
        final_report_summary_path = self._write_final_report_summary(
            run_id=run_id,
            status=run_status,
            review_status=review_status,
            final_report_path=final_report_path,
            status_payload=status_payload,
        )
        run_loop_summary_path = self._write_run_loop_summary(
            run_id=run_id,
            steps=steps,
            status_payload=status_payload,
            stop_reason="runtime_managed_validation_probe_evidence_recorded",
        )
        progress.conclusion(
            run_id=run_id,
            phase="result",
            title="Validation probe evidence recorded",
            summary=(
                "Runtime-managed validation probe evidence was recorded; ordinary "
                "debug/review/compact flow was skipped for targeted evaluation."
            ),
            artifact_refs=[str(final_report_path)],
        )
        self._emit_final_report_progress_event(
            progress,
            run_id=run_id,
            final_report_path=final_report_path,
            final_report_summary_path=final_report_summary_path,
        )
        return self._build_run_result(
            run_id=run_id,
            status=run_status,
            final_report_path=final_report_path,
            steps=steps,
            run_loop_summary_path=run_loop_summary_path,
        )

    def _runtime_managed_validation_probe_has_evidence(self, run_id: str) -> bool:
        selected = set(self.validation_probe_ids)
        if not selected:
            return False
        run_dir = self.root / ".asteria" / "runs" / run_id
        if "repair_replan_path" in selected:
            decisions = self.jsonl.read_all(run_dir / "agent_loop_decisions.jsonl")
            executions = self.jsonl.read_all(run_dir / "agent_loop_execution_results.jsonl")
            if any(
                isinstance(item, dict)
                and (item.get("next_action") or {}).get("action") in {"repair", "replan"}
                for item in decisions
            ) and any(
                isinstance(item, dict) and item.get("action") in {"repair", "replan"}
                for item in executions
            ):
                return True
        if "ask_stop_path" in selected:
            decisions = self.jsonl.read_all(run_dir / "agent_loop_decisions.jsonl")
            executions = self.jsonl.read_all(run_dir / "agent_loop_execution_results.jsonl")
            if any(
                isinstance(item, dict)
                and (item.get("next_action") or {}).get("action") in {"ask", "stop"}
                for item in decisions
            ) and any(
                isinstance(item, dict) and item.get("action") in {"ask", "stop"}
                for item in executions
            ):
                return True
        if "context_pressure_path" in selected:
            snapshots = self.jsonl.read_all(run_dir / "context_budget_snapshots.jsonl")
            if any(
                isinstance(item, dict)
                and (
                    item.get("pressure_status") in {"near_limit", "hard_stop"}
                    or (item.get("compact_boundary") or {}).get("status")
                    in {"recommended", "required", "completed"}
                )
                for item in snapshots
            ):
                return True
        if "capability_selection_path" in selected:
            decisions = self.jsonl.read_all(run_dir / "capability_decisions.jsonl")
            mcp_invocations = self.jsonl.read_all(run_dir / "mcp_invocations.jsonl")
            skill_invocations = self.jsonl.read_all(run_dir / "skill_invocations.jsonl")
            has_reasoned_decision = any(
                isinstance(item, dict) and bool((item.get("decision") or {}).get("reason"))
                for item in decisions
            )
            has_adapter_reason = any(
                isinstance(item, dict)
                and bool((item.get("capability_decision") or {}).get("reason"))
                for item in [*mcp_invocations, *skill_invocations]
            )
            if has_reasoned_decision and has_adapter_reason:
                return True
        return False

    def _build_run_result(
        self,
        *,
        run_id: str,
        status: str,
        final_report_path: Path,
        steps: list[RunStepSummary],
        status_payload: dict | None = None,
        run_loop_summary_path: Path | None = None,
    ) -> RunResult:
        status_payload = status_payload or self._status_payload(run_id)
        final_summary_path = self.root / ".asteria" / "runs" / run_id / "final_report_summary.json"
        final_summary = self._read_final_report_summary(final_summary_path)
        return RunResult(
            run_id=run_id,
            status=status,
            final_report_path=final_report_path,
            final_report_summary_path=final_summary_path if final_summary else None,
            final_report_summary=final_summary,
            steps=steps,
            run_loop_summary_path=run_loop_summary_path,
            workflow_state=self._optional_str(status_payload.get("workflow_state")),
            current_phase=self._optional_str(status_payload.get("current_phase")),
            current_blocker=self._optional_str(status_payload.get("current_blocker")),
            recommended_next_command=self._optional_str(
                status_payload.get("recommended_next_command")
            ),
            next_actions=self._string_list(status_payload.get("next_actions")),
        )

    def _status_payload(self, run_id: str) -> dict:
        try:
            payload = StatusCommand(self.root).run().to_dict()
        except Exception:  # noqa: BLE001
            payload = {}
        if payload.get("current_session_id") != run_id:
            return self._status_payload_for_session(run_id)
        return payload

    def _status_payload_for_session(self, run_id: str) -> dict:
        try:
            sessions = SessionsCommand(
                self.root,
                session_id=run_id,
                include_context=True,
            ).run()
            context = sessions.context.get(run_id) or {}
            return StatusResult(
                root=self.root,
                initialized=True,
                current_session_id=run_id,
                current_context=context,
                recent_sessions=sessions.sessions,
                plugin_control=plugin_control_summary(self.root, self.validator),
            ).to_dict()
        except Exception:  # noqa: BLE001
            return {}

    def _optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _read_final_report_summary(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, "final_report_summary")

    def _write_final_report_summary(
        self,
        *,
        run_id: str,
        status: str,
        review_status: str,
        final_report_path: Path,
        status_payload: dict,
    ) -> Path:
        run_dir = self.root / ".asteria" / "runs" / run_id
        current_blocker = self._optional_str(status_payload.get("current_blocker"))
        recommended = self._optional_str(status_payload.get("recommended_next_command"))
        model_route_timeline_path = self._write_model_route_timeline(run_id)
        model_route_timeline = self._model_route_timeline(run_dir, limit=20)
        workspace_envelope = self._workspace_envelope(run_dir)
        validation_conclusion = self._validation_conclusion(run_dir)
        file_changes = self._file_change_summary(run_dir)
        todo_view = self._todo_view(run_dir, validation_conclusion=validation_conclusion)
        task_plan = self._read_json_if_exists(run_dir / "task_plan.json", "task_board")
        tasks = task_plan.get("tasks") if isinstance(task_plan, dict) else []
        task_count = len(tasks or [])
        done_count = len(
            [
                task
                for task in tasks or []
                if isinstance(task, dict) and task.get("status") in {"done", "discarded"}
            ]
        )
        execution_evidence = self._execution_evidence(run_dir)
        workflow_state = self._optional_str(status_payload.get("workflow_state"))
        status_payload_with_todo = {
            **status_payload,
            "run_status": status_payload.get("run_status") or self._run_record_summary(run_id),
            "task_summary": status_payload.get("task_summary")
            or {"total": task_count, "remaining": task_count - done_count},
            "latest_execution_evidence": (
                status_payload.get("latest_execution_evidence")
                or (execution_evidence[-1] if execution_evidence else {})
            ),
            "workspace_envelope": workspace_envelope,
            "todo_view": todo_view,
            "run_loop_summary_path": (
                f".asteria/runs/{run_id}/run_loop_summary.json"
                if (run_dir / "run_loop_summary.json").exists()
                else None
            ),
            "final_report_summary_path": f".asteria/runs/{run_id}/final_report_summary.json",
            "model_route_timeline_path": (
                f".asteria/runs/{run_id}/model_route_timeline.json"
                if (run_dir / "model_route_timeline.json").exists()
                else None
            ),
        }
        main_path = build_main_path(
            workflow_state=workflow_state,
            recommended_next_command=recommended,
            current_blocker=current_blocker,
            context=status_payload_with_todo,
            validation_conclusion=validation_conclusion,
        )
        recommended = canonical_next_command(main_path, recommended)
        runtime_progress = build_runtime_progress(
            workflow_state=workflow_state,
            main_path=main_path,
            todo_view=todo_view,
            latest_execution=status_payload_with_todo.get("latest_execution_evidence") or {},
            latest_decision=status_payload_with_todo.get("latest_agent_loop_decision") or {},
            latest_execution_result=status_payload_with_todo.get(
                "latest_agent_loop_execution_result"
            )
            or {},
            latest_observation=status_payload_with_todo.get("latest_agent_loop_observation") or {},
            agent_loop_summary=status_payload_with_todo.get("agent_loop_run_summary") or {},
            validation_conclusion=validation_conclusion,
        )
        summary = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "status": status,
            "review_status": review_status,
            "final_report_path": final_report_path.relative_to(self.root).as_posix(),
            "workspace_envelope": workspace_envelope,
            "output_locations": self._output_locations(workspace_envelope),
            "workflow_state": workflow_state,
            "current_blocker": current_blocker,
            "recommended_next_command": recommended,
            "main_path": main_path,
            "todo_view": todo_view,
            "runtime_progress": runtime_progress,
            "model_selection": self._latest_model_selection(run_dir),
            "model_route_timeline_path": (
                model_route_timeline_path.relative_to(self.root).as_posix()
                if model_route_timeline_path
                else None
            ),
            "model_route_timeline": model_route_timeline,
            "file_changes": file_changes,
            "validation_conclusion": validation_conclusion,
            "blockers": self._string_list(status_payload.get("blockers")),
            "next_actions": self._string_list(status_payload.get("next_actions")),
            "goal_policy": self._goal_policy_summary(run_dir, status_payload),
            "updated_at": now_iso(),
        }
        path = run_dir / "final_report_summary.json"
        self.store.write(path, summary, "final_report_summary")
        self._write_active_goal_memory(
            run_id=run_id,
            review_status=review_status,
            blockers=self._string_list(status_payload.get("blockers")),
            next_actions=self._string_list(status_payload.get("next_actions")),
        )
        return path

    def _write_model_route_timeline(self, run_id: str) -> Path | None:
        run_dir = self.root / ".asteria" / "runs" / run_id
        timeline = self._model_route_timeline(run_dir, limit=None)
        if not timeline:
            return None
        path = run_dir / "model_route_timeline.json"
        self.store.write(
            path,
            {
                "schema_version": "0.1.0",
                "run_id": run_id,
                "record_count": len(timeline),
                "timeline": timeline,
                "updated_at": now_iso(),
            },
            "model_route_timeline",
        )
        return path

    def _write_run_loop_summary(
        self,
        *,
        run_id: str,
        steps: list[RunStepSummary],
        status_payload: dict,
        stop_reason: str,
    ) -> Path:
        run_dir = self.root / ".asteria" / "runs" / run_id
        task_plan = self._task_plan_for_main_path(run_dir)
        latest_execution = self._latest_execution_evidence(run_dir)
        validation_conclusion = self._validation_conclusion(run_dir)
        run_status = self._run_record_summary(run_id)
        todo_view = self._todo_view(
            run_dir,
            task_plan=task_plan,
            latest_execution=latest_execution,
            validation_conclusion=validation_conclusion,
        )
        enriched_status = {
            **status_payload,
            "run_status": run_status,
            "task_summary": self._task_summary_for_main_path(task_plan),
            "latest_execution_evidence": latest_execution,
            "workspace_envelope": self._workspace_envelope(run_dir),
            "todo_view": todo_view,
            "run_loop_summary_path": f".asteria/runs/{run_id}/run_loop_summary.json",
            "final_report_summary_path": (
                f".asteria/runs/{run_id}/final_report_summary.json"
                if (run_dir / "final_report_summary.json").exists()
                else None
            ),
            "model_route_timeline_path": (
                f".asteria/runs/{run_id}/model_route_timeline.json"
                if (run_dir / "model_route_timeline.json").exists()
                else None
            ),
        }
        main_path = build_main_path(
            workflow_state=self._optional_str(enriched_status.get("workflow_state")),
            recommended_next_command=self._optional_str(
                enriched_status.get("recommended_next_command")
            ),
            current_blocker=self._optional_str(enriched_status.get("current_blocker")),
            context=enriched_status,
            validation_conclusion=validation_conclusion,
        )
        recommended = canonical_next_command(
            main_path,
            self._optional_str(enriched_status.get("recommended_next_command")),
        )
        runtime_progress = build_runtime_progress(
            workflow_state=self._optional_str(enriched_status.get("workflow_state")),
            main_path=main_path,
            todo_view=todo_view,
            latest_execution=latest_execution,
            latest_decision=enriched_status.get("latest_agent_loop_decision") or {},
            latest_execution_result=enriched_status.get("latest_agent_loop_execution_result") or {},
            latest_observation=enriched_status.get("latest_agent_loop_observation") or {},
            agent_loop_summary=enriched_status.get("agent_loop_run_summary") or {},
            validation_conclusion=validation_conclusion,
        )
        summary = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "iteration_count": self._iteration_count(steps),
            "stop_reason": stop_reason,
            "latest_evidence": self._latest_evidence_pointer(run_dir),
            "workflow_state": self._optional_str(status_payload.get("workflow_state")),
            "current_blocker": self._optional_str(status_payload.get("current_blocker")),
            "recommended_next_command": recommended,
            "main_path": main_path,
            "runtime_progress": runtime_progress,
            "updated_at": now_iso(),
        }
        path = run_dir / "run_loop_summary.json"
        self.store.write(path, summary, "run_loop_summary")
        return path

    def _iteration_count(self, steps: list[RunStepSummary]) -> int:
        iterations = set()
        for step in steps:
            if step.name != "execute":
                continue
            prefix = "Iteration "
            if not step.summary.startswith(prefix):
                continue
            raw = step.summary[len(prefix) :].split(":", 1)[0]
            if raw.isdigit():
                iterations.add(int(raw))
        return len(iterations)

    def _stop_reason(self, steps: list[RunStepSummary], *, max_iterations: int) -> str:
        if not steps:
            return "no_steps_recorded"
        last = steps[-1]
        if any(step.name == "decide" and step.status == "paused" for step in steps):
            return "decision_required"
        if any(step.name == "observe" and step.status in {"ask", "stop"} for step in steps):
            return "agent_observation_requires_user"
        if any(step.status == "budget_guard" for step in steps):
            return "budget_guard_compacted"
        if any(step.name == "execute" and step.status == "stopped" for step in steps):
            return "no_ready_task_progress"
        review_steps = [step for step in steps if step.name == "review"]
        if review_steps:
            review = review_steps[-1]
            if review.status == "pass":
                return "review_passed"
            if "0 follow-up task(s)" in review.summary:
                return "review_no_followups"
        if self._iteration_count(steps) >= max_iterations and max_iterations > 0:
            return "max_iterations_reached"
        if last.name == "compact":
            return "handoff_written"
        return f"{last.name}_{last.status}"

    def _latest_evidence_pointer(self, run_dir: Path) -> dict | None:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            return None
        evidence_items = self.jsonl.read_all(path, "task_execution_evidence")
        if not evidence_items:
            return None
        latest = evidence_items[-1]
        return {
            "path": path.relative_to(self.root).as_posix(),
            "task_id": str(latest.get("task_id") or ""),
            "status": str(latest.get("status") or ""),
            "summary": str(latest.get("summary") or ""),
            "evidence_id": latest.get("evidence_id"),
        }

    def _emit_workspace_progress_event(
        self,
        progress: UserProgressLogger,
        run_id: str,
        *,
        phase: str,
    ) -> None:
        run_dir = self.root / ".asteria" / "runs" / run_id
        envelope = self._workspace_envelope(run_dir)
        if not envelope:
            return
        output_locations = self._output_locations(envelope)
        progress.workspace_event(
            run_id=run_id,
            title="Workspace and outputs selected",
            summary=self._workspace_progress_summary(output_locations),
            workspace=envelope,
            output_locations=output_locations,
            phase=phase,
        )

    def _workspace_progress_summary(self, output_locations: dict) -> str:
        input_count = len(output_locations.get("input_roots") or [])
        return (
            f"Workspace {output_locations.get('workspace_root') or self.root}; "
            f"{input_count} input root(s); output {output_locations.get('output_root')}; "
            f"artifacts {output_locations.get('artifact_root')}."
        )

    def _emit_execution_progress_events(
        self,
        progress: UserProgressLogger,
        run_id: str,
        *,
        phase: str,
    ) -> None:
        run_dir = self.root / ".asteria" / "runs" / run_id
        model_selection = self._latest_model_selection(run_dir)
        if model_selection:
            progress.model_decision_event(
                run_id=run_id,
                phase=phase,
                title="Model route decision",
                summary=self._model_selection_summary(model_selection),
                model_selection=model_selection,
            )
        file_changes = self._file_change_summary(run_dir)
        if file_changes:
            progress.file_change_event(
                run_id=run_id,
                phase=phase,
                title="File changes captured",
                summary=f"{len(file_changes)} changed file(s) are now visible in the run timeline.",
                file_changes=file_changes,
                artifact_refs=[item["path"] for item in file_changes if item.get("path")],
            )
        validation = self._validation_conclusion(run_dir)
        if validation["status"] != "not_recorded":
            progress.validation_event(
                run_id=run_id,
                phase="review" if phase == "review" else "execute",
                title="Validation conclusion",
                summary=validation["summary"],
                validation=validation,
                status="failed" if validation["status"] == "failed" else "completed",
                evidence_refs=validation.get("evidence_refs") or [],
            )

    def _emit_final_report_progress_event(
        self,
        progress: UserProgressLogger,
        *,
        run_id: str,
        final_report_path: Path,
        final_report_summary_path: Path,
    ) -> None:
        run_dir = self.root / ".asteria" / "runs" / run_id
        workspace_envelope = self._workspace_envelope(run_dir)
        validation = self._validation_conclusion(run_dir)
        file_changes = self._file_change_summary(run_dir)
        progress.final_report_event(
            run_id=run_id,
            title="Final report written",
            summary=(
                "The final report and structured summary are available at the recorded output "
                "locations."
            ),
            final_report_path=str(final_report_path),
            final_report_summary_path=str(final_report_summary_path),
            output_locations=self._output_locations(workspace_envelope),
            validation=validation,
            model_selection=self._latest_model_selection(run_dir),
            file_changes=file_changes,
        )

    def _model_selection_summary(self, model_selection: dict) -> str:
        selected = model_selection.get("selected_tier") or "unknown"
        purpose = model_selection.get("purpose") or "unknown"
        reason = model_selection.get("reason") or "No reason recorded."
        pressure = model_selection.get("tier_pressure") or {}
        if pressure:
            return (
                f"Selected {selected} for {purpose}: {reason} "
                f"({pressure.get('default_tier', 'unknown')} -> {selected})."
            )
        return f"Selected {selected} for {purpose}: {reason}."

    def _file_change_summary(self, run_dir: Path) -> list[dict[str, str]]:
        changes: dict[str, dict[str, str]] = {}
        artifact_log = run_dir / "artifacts.jsonl"
        if artifact_log.exists():
            for artifact in self.jsonl.read_all(artifact_log, "artifact"):
                path = str(artifact.get("path") or "")
                if not path:
                    continue
                changes[path] = {
                    "path": path,
                    "operation": "modified",
                    "source": "artifact",
                    "artifact_id": str(artifact.get("artifact_id") or ""),
                    "summary": str(artifact.get("summary") or ""),
                }
        evidence_log = run_dir / "task_execution_evidence.jsonl"
        if evidence_log.exists():
            for evidence in self.jsonl.read_all(evidence_log, "task_execution_evidence"):
                candidate = evidence.get("candidate") or {}
                for path in candidate.get("promoted_files") or []:
                    text_path = str(path)
                    changes[text_path] = {
                        "path": text_path,
                        "operation": "promoted",
                        "source": "task_execution_evidence",
                        "task_id": str(evidence.get("task_id") or ""),
                        "summary": str(evidence.get("summary") or ""),
                    }
        return list(changes.values())[-20:]

    def _todo_view(
        self,
        run_dir: Path,
        *,
        task_plan: dict | None = None,
        latest_execution: dict | None = None,
        validation_conclusion: dict | None = None,
    ) -> dict:
        loaded_task_plan = task_plan or self._read_json_if_exists(
            run_dir / "task_plan.json",
            "task_board",
        )
        try:
            model_todos = self._read_unvalidated_json(run_dir / "model_todos.json")
        except json.JSONDecodeError:
            model_todos = {}
        latest = latest_execution
        if latest is None:
            evidence = self._execution_evidence(run_dir)
            latest = evidence[-1] if evidence else {}
        validation = validation_conclusion or self._validation_conclusion(run_dir)
        return build_todo_view(
            task_plan=loaded_task_plan,
            model_todos=model_todos,
            latest_execution=latest,
            validation_conclusion=validation,
        )

    def _validation_conclusion(self, run_dir: Path) -> dict[str, Any]:
        validation_path = run_dir / "validation_results.jsonl"
        validations = (
            self.jsonl.read_all(validation_path, "validation_result")
            if validation_path.exists()
            else []
        )
        verification_calls = self._verification_evidence(run_dir)
        passed_validations = [item for item in validations if item.get("status") == "passed"]
        failed_validations = [item for item in validations if item.get("status") == "failed"]
        passed_commands = [item for item in verification_calls if item.get("status") == "success"]
        failed_commands = [item for item in verification_calls if item.get("status") != "success"]
        total = len(validations) + len(verification_calls)
        passed = len(passed_validations) + len(passed_commands)
        failed = len(failed_validations) + len(failed_commands)
        if total == 0:
            status = "not_recorded"
            summary = "No validation or verification command has been recorded yet."
        elif failed:
            status = "failed"
            summary = f"Validation has failures: {passed}/{total} check(s) passed."
        else:
            status = "passed"
            summary = f"Validation passed: {passed}/{total} check(s) passed."
        refs: list[str] = []
        if validations:
            refs.append(validation_path.relative_to(self.root).as_posix())
        if verification_calls:
            refs.append((run_dir / "tool_calls.jsonl").relative_to(self.root).as_posix())
        return {
            "status": status,
            "summary": summary,
            "total": total,
            "passed": passed,
            "failed": failed,
            "validation_result_count": len(validations),
            "verification_command_count": len(verification_calls),
            "evidence_refs": refs,
        }

    def _execute_until_no_ready(
        self,
        run_id: str,
        steps: list[RunStepSummary],
        iteration: int,
        progress: UserProgressLogger | None = None,
    ) -> bool:
        progressed = False
        while self._ready_count(run_id) > 0:
            execute = ExecuteCommand(
                self.root,
                run_id=run_id,
                max_tasks=self.max_tasks_per_iteration,
                model_client=self.execute_model_client or self.model_client,
                parallel_readonly=self.parallel_writes,
                parallel_writes=self.parallel_writes,
            ).run()
            progressed = progressed or execute.completed > 0 or execute.blocked > 0
            steps.append(
                RunStepSummary(
                    "execute",
                    "completed",
                    (
                        f"Iteration {iteration}: {execute.completed} completed, "
                        f"{execute.blocked} blocked."
                    ),
                )
            )
            if progress:
                progress.record(
                    run_id=run_id,
                    channel="progress",
                    phase="execute",
                    status="running",
                    title="任务执行进展",
                    summary=(
                        f"迭代 {iteration}：完成 {execute.completed} 个任务，"
                        f"阻塞 {execute.blocked} 个任务。"
                    ),
                    display_level="main",
                )
            status = self._run_status(run_id)
            if self._ready_count(run_id) > 0 and self._task_plan_quality_gate(run_id, steps):
                return progressed
            if self._runtime_managed_validation_probe_has_evidence(run_id):
                return progressed
            if status == "blocked":
                if progress:
                    progress.record(
                        run_id=run_id,
                        channel="progress",
                        phase="execute",
                        status="running",
                        title="调试阶段",
                        summary="检测到阻塞任务，正在分析失败原因并尝试修复。",
                        display_level="main",
                    )
                debug = DebugCommand(
                    self.root,
                    run_id=run_id,
                    model_client=self.debug_model_client or self.model_client,
                ).run()
                steps.append(
                    RunStepSummary(
                        "debug",
                        "completed",
                        (f"{debug.repaired} repaired, {debug.still_blocked} still blocked."),
                    )
                )
                if progress:
                    progress.record(
                        run_id=run_id,
                        channel="progress",
                        phase="execute",
                        status="running",
                        title="调试完成",
                        summary=f"修复 {debug.repaired} 个任务，仍阻塞 {debug.still_blocked} 个。",
                        display_level="main",
                    )
                if self._run_status(run_id) == "blocked":
                    blocked_route = self._blocked_route_from_observation_plan(run_id)
                    if blocked_route in {"ask", "stop"}:
                        steps.append(
                            RunStepSummary(
                                "observe",
                                blocked_route,
                                (
                                    "Observation plan selected "
                                    f"{blocked_route}; not replanning automatically."
                                ),
                            )
                        )
                        return progressed
                    if self._budget_guard(run_id, steps, f"iteration-{iteration}-replan"):
                        return progressed
                    replan = ReplanCommand(
                        self.root,
                        run_id=run_id,
                        max_replans_per_task=self._policy_replans_per_task(),
                    ).run()
                    steps.append(
                        RunStepSummary(
                            "replan",
                            "completed",
                            (
                                f"{replan.created_tasks} task(s), "
                                f"{replan.created_decisions} decision(s)."
                            ),
                        )
                    )
                    if replan.created_tasks:
                        progressed = True
                        continue
                    return progressed
            if execute.completed == 0 and execute.blocked == 0:
                steps.append(
                    RunStepSummary(
                        "execute",
                        "stopped",
                        "No ready task made progress; stopping the run loop.",
                    )
                )
                return progressed
        return progressed

    def _emit_agent_loop_dispatch(
        self,
        progress: UserProgressLogger,
        run_id: str,
        *,
        phase: str,
    ) -> dict:
        run_dir = self.root / ".asteria" / "runs" / run_id
        task_plan = self.store.read(run_dir / "task_plan.json", "task_board")
        workspace = self._workspace_envelope(run_dir)
        permission_mode = str(workspace.get("permission_mode") or self.permission_level)
        dispatch = AgentLoopProfileRegistry().dispatch_plan(
            list(task_plan.get("tasks") or []),
            permission_mode=permission_mode,
        )
        dispatch_path = run_dir / "agent_loop_dispatch.json"
        dispatch_path.write_text(
            json.dumps(dispatch, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        progress.record(
            run_id=run_id,
            channel="evidence",
            event_type="evidence",
            phase=phase,
            status="running",
            title="Agent loop dispatch loaded",
            summary=(
                f"Runtime selected loop profiles before execution: {dispatch['profile_counts']}."
            ),
            display_level="inspector",
            artifact_refs=[str(dispatch_path)],
            evidence_refs=[str(dispatch_path)],
            call_chain=["RunCommand", "AgentLoopProfileRegistry"],
            execution_chain=["agent_loop_dispatch", phase],
            data={"agent_loop_dispatch": dispatch},
        )
        return dispatch

    def _budget_guard(self, run_id: str, steps: list[RunStepSummary], phase: str) -> bool:
        policy = self._policy()
        report = self._cost_report(run_id)
        pressure = BudgetController.pressure(policy, report)
        if pressure["status"] in {"within_budget"}:
            return False
        if pressure["status"] == "near_limit":
            if int(report.get("context_compactions", 0)) == 0:
                compact = CompactCommand(
                    self.root,
                    run_id=run_id,
                    focus=f"budget guard before {phase}",
                ).run()
                steps.append(
                    RunStepSummary(
                        "compact",
                        "budget_guard",
                        f"Near budget; snapshot: {compact.snapshot_path.name}.",
                    )
                )
            return False
        if self._pending_budget_decision(run_id):
            self._pause_run_for_budget(run_id, "Budget guard waiting for an existing decision.")
            self._write_goal_policy_marker(
                run_id,
                {
                    "category": "budget_guard",
                    "recommended_command": "decide --list",
                    "reason": "Budget guard is waiting for an existing DecisionPoint.",
                },
            )
            return True
        decision = self._create_budget_decision(run_id, pressure, phase)
        self._pause_run_for_budget(
            run_id,
            f"Budget guard paused before {phase}: {decision['decision_id']}.",
        )
        self._write_goal_policy_marker(
            run_id,
            {
                "category": "budget_guard",
                "recommended_command": "decide --list",
                "reason": (
                    f"Budget guard reached {pressure['status']} before {phase}; "
                    f"{pressure['highest_label']} at {pressure['highest_ratio']:.0%}."
                ),
                "decision_id": decision["decision_id"],
            },
        )
        steps.append(
            RunStepSummary(
                "decide",
                "paused",
                f"Budget guard created {decision['decision_id']} before {phase}.",
            )
        )
        return True

    def _task_plan_quality_gate(
        self,
        run_id: str,
        steps: list[RunStepSummary],
    ) -> bool:
        result = TaskPlanQualityGate(self.root, self.validator).check(
            run_id,
            pause_run=True,
            blocking=self._task_plan_quality_gate_blocks(),
        )
        if not result.blocked:
            if result.task_plan_eval and result.task_plan_eval.get("status") == "fail":
                steps.append(
                    RunStepSummary(
                        "plan-quality",
                        "warning",
                        (
                            "Task plan quality failed but was kept as a repairable "
                            "agent-loop warning before execution."
                        ),
                    )
                )
            return False
        task_plan_eval = result.task_plan_eval or {}
        decision = result.decision or {"decision_id": "unknown"}
        steps.append(
            RunStepSummary(
                "decide",
                "paused",
                (
                    f"Task plan quality failed "
                    f"({task_plan_eval['overall_score']:.2f}); "
                    f"created {decision['decision_id']} before execution."
                ),
            )
        )
        return True

    def _task_plan_quality_gate_blocks(self) -> bool:
        policy = self._policy()
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("task_plan_quality_gate_blocks", False))

    def _refresh_task_plan_eval(
        self,
        run_id: str,
        run_dir: Path,
        eval_path: Path,
    ) -> dict | None:
        return TaskPlanQualityGate(self.root, self.validator).refresh(run_id, run_dir, eval_path)

    def _task_plan_quality_bypassed(self, decisions: list[dict], task_plan_eval: dict) -> bool:
        for decision in decisions:
            if decision["status"] not in {"resolved", "defaulted"}:
                continue
            option = self._selected_decision_option(decision)
            metadata = decision.get("metadata") or {}
            if (
                option
                and option.get("action") == "record_constraint"
                and metadata.get("status") == task_plan_eval["status"]
                and metadata.get("overall_score") == task_plan_eval["overall_score"]
                and metadata.get("issue_codes") == self._task_plan_issue_codes(task_plan_eval)
            ):
                return True
        return False

    def _active_task_plan_revision(self, run_id: str, decisions: list[dict]) -> bool:
        revision_decision_ids = {
            decision["decision_id"]
            for decision in decisions
            if decision["status"] in {"resolved", "defaulted"}
            and (self._selected_decision_option(decision) or {}).get("action") == "require_replan"
        }
        if not revision_decision_ids:
            return False
        task_plan_path = self.root / ".asteria" / "runs" / run_id / "task_plan.json"
        if not task_plan_path.exists():
            return False
        task_plan = self.store.read(task_plan_path, "task_board")
        active_statuses = {"ready", "backlog", "in_progress", "testing", "reviewing", "blocked"}
        for task in task_plan["tasks"]:
            if task["status"] not in active_statuses:
                continue
            notes = str(task.get("notes") or "")
            if any(decision_id in notes for decision_id in revision_decision_ids):
                return True
        return False

    def _selected_decision_option(self, decision: dict) -> dict | None:
        selected = decision.get("selected_option_id") or decision.get("default_option_id")
        for option in decision.get("options", []):
            if option.get("option_id") == selected:
                return option
        return None

    def _task_plan_issue_codes(self, task_plan_eval: dict) -> list[str]:
        return [
            str(issue.get("code"))
            for issue in task_plan_eval.get("issues", [])[:10]
            if isinstance(issue, dict)
        ]

    def _task_plan_quality_decisions(self, run_id: str) -> list[dict]:
        run_dir = self.root / ".asteria" / "runs" / run_id
        return [
            decision
            for decision in self._decisions(run_dir)
            if (decision.get("metadata") or {}).get("kind") == "task_plan_quality_gate"
        ]

    def _create_task_plan_quality_decision(
        self,
        run_id: str,
        task_plan_eval: dict,
        eval_path: Path,
    ) -> dict:
        issue_summary = self._task_plan_issue_summary(task_plan_eval)
        options = [
            {
                "option_id": "revise_plan",
                "label": "Revise plan first",
                "tradeoff": "Spend a planning iteration before execution to avoid unverifiable work.",
                "action": "require_replan",
            },
            {
                "option_id": "proceed_once",
                "label": "Proceed once",
                "tradeoff": "Bypass this gate once, accepting higher risk of wasted execution.",
                "action": "record_constraint",
            },
        ]
        result = DecideCommand(
            self.root,
            run_id=run_id,
            question=(
                "Task plan quality failed before execution. "
                f"Score: {task_plan_eval['overall_score']:.2f}. "
                f"Issues: {issue_summary}. Revise the plan first?"
            ),
            options_json=json.dumps(options, ensure_ascii=False),
            recommended_option_id="revise_plan",
            default_option_id="revise_plan",
            impact_json=json.dumps(
                {"scope": "medium", "budget": "medium", "risk": "high", "quality": "high"},
                ensure_ascii=False,
            ),
            metadata={
                "kind": "task_plan_quality_gate",
                "task_plan_eval": str(eval_path),
                "status": task_plan_eval["status"],
                "overall_score": task_plan_eval["overall_score"],
                "issue_count": len(task_plan_eval.get("issues", [])),
                "issue_codes": self._task_plan_issue_codes(task_plan_eval),
            },
        ).run()
        return result.decisions[0]

    def _task_plan_issue_summary(self, task_plan_eval: dict) -> str:
        issues = [
            str(issue.get("code"))
            for issue in task_plan_eval.get("issues", [])[:5]
            if isinstance(issue, dict) and issue.get("code")
        ]
        if not issues:
            return "no issue details recorded"
        extra = len(task_plan_eval.get("issues", [])) - len(issues)
        suffix = f", +{extra} more" if extra > 0 else ""
        return ", ".join(issues) + suffix

    def _pause_run_for_task_plan_quality(self, run_id: str, summary: str) -> None:
        run_store = RunStore(self.root / ".asteria", self.validator)
        run = run_store.load_run(run_id)
        run["status"] = "paused"
        run["current_phase"] = "DECISION"
        run["summary"] = summary
        run_store.update_run(run)

    def _goal_loop_decision(
        self,
        *,
        run_id: str,
        review_status: str,
        follow_up_count: int,
        decision_count: int,
        iteration: int,
        max_iterations: int,
    ) -> dict[str, object]:
        failure_classification = self._review_failure_classification(run_id)
        if decision_count or self._pending_decisions(self.root / ".asteria" / "runs" / run_id):
            return {
                "action": "stop_for_decision",
                "reason": "DecisionPoint is pending; stop instead of guessing or continuing.",
                "category": "decision_required",
                "recommended_command": "decide --list",
            }
        if self._pending_budget_decision(run_id):
            return {
                "action": "stop_for_decision",
                "reason": "Budget guard DecisionPoint is pending; user approval is required.",
                "category": "decision_required",
                "recommended_command": "decide --list",
            }
        pending_promotions = CandidatePromotionQueue(self.validator).summary(
            self.root / ".asteria" / "runs" / run_id
        )
        promotion_blockers = list(pending_promotions.get("pending") or []) + list(
            pending_promotions.get("blocked") or []
        )
        if review_status == "pass":
            if (
                normalize_permission_mode(self.permission_level) == "auto"
                and not promotion_blockers
            ):
                return {
                    "action": "auto_accept",
                    "reason": "Review passed, permission level is auto, and no candidate promotion requires approval.",
                    "category": "none",
                    "recommended_command": "accept",
                }
            if promotion_blockers:
                return {
                    "action": "stop_for_accept",
                    "reason": "Review passed but candidate promotion still requires explicit accept/promotion handling.",
                    "category": "acceptance_required",
                    "recommended_command": "accept",
                }
            return {
                "action": "stop_for_accept",
                "reason": "Review passed; ask/balanced permission requires explicit `asteria accept`.",
                "category": "acceptance_required",
                "recommended_command": "accept",
            }
        if failure_classification.get("recommended_command") == "decide --list":
            return {
                "action": "stop_for_decision",
                "reason": str(failure_classification.get("reason") or "Decision is required."),
                "category": failure_classification.get("category") or "decision_required",
                "recommended_command": "decide --list",
            }
        if failure_classification.get("recommended_command") == "replan":
            return {
                "action": "stop_for_replan",
                "reason": str(
                    failure_classification.get("reason") or "Review identified a plan gap."
                ),
                "category": failure_classification.get("category") or "plan_gap",
                "recommended_command": "replan",
            }
        if follow_up_count > 0 and iteration < max_iterations:
            return {
                "action": "continue_repair",
                "reason": "Review created follow-up tasks; continue bounded repair loop.",
                "category": failure_classification.get("category") or "repairable_follow_up",
                "recommended_command": "debug",
            }
        return {
            "action": "stop_for_repair",
            "reason": str(
                failure_classification.get("reason")
                or f"Review status is {review_status}; run debug before continuing."
            ),
            "category": failure_classification.get("category") or "review_failed",
            "recommended_command": failure_classification.get("recommended_command") or "debug",
        }

    def _review_failure_classification(self, run_id: str) -> dict:
        eval_path = self.root / ".asteria" / "runs" / run_id / "eval_report.json"
        if not eval_path.exists():
            return {}
        report = self.store.read(eval_path, "eval_report")
        classification = (report.get("trajectory_eval") or {}).get("failure_classification")
        return classification if isinstance(classification, dict) else {}

    def _goal_policy_summary(self, run_dir: Path, status_payload: dict) -> dict:
        context_policy = (
            (status_payload.get("current_context") or {}).get("goal_policy")
            if isinstance(status_payload.get("current_context"), dict)
            else None
        )
        if isinstance(context_policy, dict) and context_policy:
            return context_policy
        marker = self._read_unvalidated_json(run_dir / "goal_policy.json")
        marker_policy = marker.get("goal_policy")
        if isinstance(marker_policy, dict) and marker_policy:
            return marker_policy
        report = self._read_json_if_exists(run_dir / "eval_report.json", "eval_report")
        policy = (report.get("trajectory_eval") or {}).get("failure_classification")
        return policy if isinstance(policy, dict) else {}

    def _read_json_if_exists(self, path: Path, schema_name: str) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _read_unvalidated_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _ready_count(self, run_id: str) -> int:
        task_plan = self.store.read(
            self.root / ".asteria" / "runs" / run_id / "task_plan.json",
            "task_board",
        )
        done = {task["task_id"] for task in task_plan["tasks"] if task["status"] == "done"}
        return len(
            [
                task
                for task in task_plan["tasks"]
                if task["status"] == "ready" and all(dep in done for dep in task["depends_on"])
            ]
        )

    def _research_context(self, report_path: Path) -> str:
        report = self.store.read(report_path, "research_report")
        lines = [report["summary"]]
        for req in report.get("expanded_requirements", [])[:5]:
            lines.append(f"- {req['priority']}: {req['description']}")
        for risk in report.get("risks", [])[:3]:
            lines.append(f"- risk: {risk['risk']} / mitigation: {risk['mitigation']}")
        return "\n".join(lines)

    def _policy_iterations(self) -> int:
        if not (self.root / ".asteria" / "policies.json").exists():
            return 8
        policy = self._policy()
        return int(policy["budgets"]["max_iterations_per_goal"])

    def _policy_replans_per_task(self) -> int:
        if not (self.root / ".asteria" / "policies.json").exists():
            return 2
        policy = self._policy()
        return int(policy["budgets"].get("max_replans_per_task", 2))

    def _policy(self) -> dict:
        return load_policy_config(self.root / ".asteria", self.validator)

    def _cost_report(self, run_id: str) -> dict:
        path = self.root / ".asteria" / "runs" / run_id / "cost_report.json"
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

    def _pending_budget_decision(self, run_id: str) -> bool:
        run_dir = self.root / ".asteria" / "runs" / run_id
        return any(
            decision["status"] == "pending"
            and (decision.get("metadata") or {}).get("kind") == "budget_guard"
            for decision in self._decisions(run_dir)
        )

    def _create_budget_decision(self, run_id: str, pressure: dict, phase: str) -> dict:
        options = [
            {
                "option_id": "continue_once",
                "label": "Continue once",
                "tradeoff": "Spend another iteration despite budget pressure.",
                "action": "record_constraint",
            },
            {
                "option_id": "stop_and_review",
                "label": "Stop and review",
                "tradeoff": "Preserve evidence and avoid further automatic cost.",
                "action": "record_constraint",
            },
        ]
        result = DecideCommand(
            self.root,
            run_id=run_id,
            question=(
                "Budget guard reached "
                f"{pressure['status']} before {phase}: "
                f"{pressure['highest_label']} at {pressure['highest_ratio']:.0%}. Continue?"
            ),
            options_json=json.dumps(options, ensure_ascii=False),
            recommended_option_id="stop_and_review",
            default_option_id="stop_and_review",
            impact_json=json.dumps(
                {"scope": "low", "budget": "high", "risk": "medium", "quality": "medium"},
                ensure_ascii=False,
            ),
            metadata={
                "kind": "budget_guard",
                "phase": phase,
                "pressure": pressure,
            },
        ).run()
        return result.decisions[0]

    def _pause_run_for_budget(self, run_id: str, summary: str) -> None:
        run_store = RunStore(self.root / ".asteria", self.validator)
        run = run_store.load_run(run_id)
        run["status"] = "paused"
        run["current_phase"] = "DECISION"
        run["summary"] = summary
        run_store.update_run(run)

    def _write_goal_policy_marker(self, run_id: str, goal_policy: dict) -> Path:
        run_dir = self.root / ".asteria" / "runs" / run_id
        marker = {
            "schema_version": "0.1.0",
            "goal_policy": goal_policy,
            "updated_at": now_iso(),
        }
        path = run_dir / "goal_policy.json"
        path.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run_status(self, run_id: str) -> str:
        run = RunStore(self.root / ".asteria", self.validator).load_run(run_id)
        return run["status"]

    def _run_record_summary(self, run_id: str) -> dict:
        run = RunStore(self.root / ".asteria", self.validator).load_run(run_id)
        return {
            "status": run.get("status"),
            "current_phase": run.get("current_phase"),
            "summary": run.get("summary"),
        }

    def _task_plan_for_main_path(self, run_dir: Path) -> dict:
        path = run_dir / "task_plan.json"
        if not path.exists():
            return {}
        return self.store.read(path, "task_board")

    def _task_summary_for_main_path(self, task_plan: dict) -> dict:
        tasks = [task for task in task_plan.get("tasks", []) if isinstance(task, dict)]
        done = len([task for task in tasks if task.get("status") == "done"])
        return {
            "total": len(tasks),
            "remaining": len(
                [task for task in tasks if task.get("status") not in {"done", "discarded"}]
            ),
            "done": done,
        }

    def _latest_execution_evidence(self, run_dir: Path) -> dict:
        execution_evidence = self._execution_evidence(run_dir)
        return execution_evidence[-1] if execution_evidence else {}

    def _task_counts(self, run_id: str) -> dict[str, int]:
        task_plan = self.store.read(
            self.root / ".asteria" / "runs" / run_id / "task_plan.json",
            "task_board",
        )
        counts: dict[str, int] = {}
        for task in task_plan["tasks"]:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        return counts

    def _latest_review_status(self, run_id: str) -> str:
        path = self.root / ".asteria" / "runs" / run_id / "eval_report.json"
        if not path.exists():
            return "unknown"
        report = self.store.read(path, "eval_report")
        return report["overall"]["status"]

    def _write_final_report(
        self,
        run_id: str,
        review_status: str,
        steps: list[RunStepSummary],
    ) -> Path:
        run_dir = self.root / ".asteria" / "runs" / run_id
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        task_plan = self.store.read(run_dir / "task_plan.json", "task_board")
        cost_report = self.store.read(run_dir / "cost_report.json", "cost_report")
        task_plan_eval = self._task_plan_eval(run_dir)
        done = len([task for task in task_plan["tasks"] if task["status"] == "done"])
        blocked_tasks = [task for task in task_plan["tasks"] if task["status"] == "blocked"]
        pending_decisions = self._pending_decisions(run_dir)
        accepted_decisions = self._accepted_decisions(run_dir)
        artifacts = self._artifact_paths(run_dir)
        execution_evidence = self._execution_evidence(run_dir)
        latest_model_selection = self._latest_model_selection(run_dir)
        latest_observation_plan = self._latest_observation_plan(run_dir)
        promotion_summary = CandidatePromotionQueue(self.validator).summary(run_dir)
        acceptance = self._latest_acceptance_report()
        verification_evidence = self._verification_evidence(run_dir)
        workspace_envelope = self._workspace_envelope(run_dir)
        completion = self._completion_state(
            done=done,
            total=len(task_plan["tasks"]),
            blocked=len(blocked_tasks),
            pending_decisions=len(pending_decisions),
            review_status=review_status,
            verification_count=len(verification_evidence),
        )
        validation_conclusion = self._validation_conclusion(run_dir)
        blockers = self._report_blockers(blocked_tasks, pending_decisions, acceptance)
        risks = self._report_risks(
            cost_report,
            task_plan_eval,
            execution_evidence,
            acceptance,
            verification_evidence,
            validation_conclusion,
        )
        next_actions = self._final_next_actions(completion, blockers, risks, acceptance)
        run = RunStore(self.root / ".asteria", self.validator).load_run(run_id)
        displayed_completion = self._display_completion_state(
            completion=completion,
            review_status=review_status,
            workflow_state=self._report_workflow_state(run),
            validation_conclusion=validation_conclusion,
        )
        report_main_path = build_main_path(
            workflow_state=self._report_workflow_state(run),
            recommended_next_command=None,
            current_blocker=blockers[0] if blockers else None,
            context={
                "run_status": run,
                "task_summary": {
                    "total": len(task_plan["tasks"]),
                    "remaining": len(task_plan["tasks"]) - done,
                },
                "latest_execution_evidence": execution_evidence[-1]
                if execution_evidence
                else {},
                "workspace_envelope": workspace_envelope,
                "todo_view": self._todo_view(
                    run_dir,
                    task_plan=task_plan,
                    latest_execution=execution_evidence[-1] if execution_evidence else {},
                    validation_conclusion=validation_conclusion,
                ),
            },
            validation_conclusion=validation_conclusion,
        )
        lines = [
            "# Final Report",
            "",
            "## Current State",
            "",
            f"- Run: {run_id}",
            f"- Goal: {goal_spec['normalized_goal']}",
            f"- Completion: {displayed_completion}",
            f"- Review status: {review_status}",
            f"- Task plan quality: {self._task_plan_quality_summary(task_plan_eval)}",
            f"- Tasks done: {done}/{len(task_plan['tasks'])}",
            f"- Blocked tasks: {len(blocked_tasks)}",
            f"- Pending decisions: {len(pending_decisions)}",
            f"- Release gate signal: {self._acceptance_summary(acceptance)}",
            f"- Model calls: {cost_report['model_calls']}",
            f"- Tool calls: {cost_report['tool_calls']}",
            "",
            "## Main Path",
            "",
            *main_path_text_lines(report_main_path),
            "",
            "## Todo",
            "",
            *todo_view_text_lines(report_main_path.get("todo_view") or {}),
            "",
            "## Workspace and Outputs",
            "",
            f"- Workspace root: {workspace_envelope.get('workspace_root') or self.root}",
            f"- Input roots: {', '.join(workspace_envelope.get('input_roots') or []) or 'unknown'}",
            f"- Output root: {workspace_envelope.get('output_root') or self.root}",
            f"- Artifact root: {workspace_envelope.get('artifact_root') or 'unknown'}",
            f"- Worktree policy: {workspace_envelope.get('worktree_policy') or workspace_envelope.get('candidate_workspace_policy') or 'unknown'}",
            f"- Permission mode: {workspace_envelope.get('permission_mode') or 'unknown'}",
            "",
            "## Steps",
            "",
        ]
        lines.extend(f"- {step.name}: {step.status} - {step.summary}" for step in steps)
        if artifacts:
            lines.extend(["", "## Artifacts", ""])
            lines.extend(f"- {path}" for path in artifacts)
        passed_verifications = [v for v in verification_evidence if v.get("status") == "success"]
        lines.extend(["", "## Verification Evidence", ""])
        if verification_evidence:
            lines.append(
                f"- Verification commands: {len(verification_evidence)} run"
                f" ({len(passed_verifications)} passed)"
            )
            for call in verification_evidence[-5:]:
                lines.append(
                    f"  - {call.get('tool_name')} [{call.get('status')}]: "
                    f"{str(call.get('output_summary', ''))[:120]}"
                )
        else:
            lines.append("- No verification commands recorded.")
        if execution_evidence:
            lines.extend(["", "## Execution Evidence", ""])
            lines.extend(
                (
                    f"- {item['task_id']}: {item['status']} - {item['summary']} "
                    f"({item['evidence_path']}; strategy={item['candidate_strategy']}; "
                    f"promoted={item['promoted_files']}; failure={item['failure_type']})"
                )
                for item in execution_evidence[-10:]
            )
        lines.extend(["", "## Model Selection", ""])
        lines.extend(self._model_selection_report_lines(latest_model_selection))
        if promotion_summary["total"]:
            lines.extend(["", "## Promotion Queue", ""])
            counts = promotion_summary["status_counts"]
            lines.append(
                "- Status: "
                + ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
            )
            for item in promotion_summary["promoted"][-5:]:
                lines.append(
                    f"- {item['promotion_id']}: {item['task_id']} promoted "
                    f"{', '.join(item.get('promoted_files') or []) or 'no files'}"
                )
            for item in promotion_summary["pending"][-5:]:
                lines.append(
                    f"- {item['promotion_id']}: {item['task_id']} pending {item['status']}"
                )
        if blockers:
            lines.extend(["", "## Blockers", ""])
            lines.extend(f"- {item}" for item in blockers)
        if risks:
            lines.extend(["", "## Risks", ""])
            lines.extend(f"- {item}" for item in risks)
        if latest_observation_plan:
            lines.extend(["", "## Latest Agent Next Action", ""])
            lines.append(f"- Route: {latest_observation_plan.get('recommended_route', 'unknown')}")
            lines.append(f"- Why: {latest_observation_plan.get('reason', 'No reason recorded.')}")
            evidence_refs = latest_observation_plan.get("evidence_refs") or []
            if evidence_refs:
                lines.append(f"- Evidence: {', '.join(str(ref) for ref in evidence_refs[:3])}")
            actions = latest_observation_plan.get("actions") or []
            if actions:
                action_names = ", ".join(
                    sorted(
                        {str(action.get("action")) for action in actions if action.get("action")}
                    )
                )
                lines.append(f"- Candidate actions: {action_names}")
        if blocked_tasks:
            lines.extend(["", "## Blocked Tasks", ""])
            lines.extend(
                f"- {task['task_id']}: {task['title']} - {task.get('notes') or 'No notes recorded'}"
                for task in blocked_tasks
            )
        if pending_decisions:
            lines.extend(["", "## Pending Decisions", ""])
            lines.extend(
                f"- {decision['decision_id']}: {decision['question']}"
                for decision in pending_decisions
            )
        if accepted_decisions:
            lines.extend(["", "## Accepted Decisions", ""])
            lines.extend(
                (
                    f"- {decision['decision_id']}: {decision['question']} "
                    f"-> {decision['selected_option_id']}"
                )
                for decision in accepted_decisions
            )
        lines.extend(
            [
                "",
                "## Next Actions",
                "",
                *[f"- {action}" for action in next_actions],
            ]
        )
        path = run_dir / "final_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._write_active_goal_memory(
            run_id=run_id,
            review_status=review_status,
            completion=completion,
            steps=steps,
            blockers=blockers,
            risks=risks,
            next_actions=next_actions,
        )
        return path

    def _write_active_goal_memory(
        self,
        *,
        run_id: str,
        review_status: str,
        completion: str | None = None,
        steps: list[RunStepSummary] | None = None,
        blockers: list[str] | None = None,
        risks: list[str] | None = None,
        next_actions: list[str] | None = None,
        updated_by: str | None = None,
        update_reason: str | None = None,
    ) -> Path | None:
        run_dir = self.root / ".asteria" / "runs" / run_id
        goal_path = run_dir / "goal_spec.json"
        task_path = run_dir / "task_plan.json"
        cost_path = run_dir / "cost_report.json"
        if not goal_path.exists() or not task_path.exists() or not cost_path.exists():
            return None
        goal_spec = self.store.read(goal_path, "goal_spec")
        task_plan = self.store.read(task_path, "task_board")
        run = RunStore(self.root / ".asteria", self.validator).load_run(run_id)
        done = len([task for task in task_plan["tasks"] if task["status"] == "done"])
        blocked_tasks = [task for task in task_plan["tasks"] if task["status"] == "blocked"]
        pending_decisions = self._pending_decisions(run_dir)
        accepted_decisions = self._accepted_decisions(run_dir)
        resolved_completion = completion or self._completion_state(
            done=done,
            total=len(task_plan["tasks"]),
            blocked=len(blocked_tasks),
            pending_decisions=len(pending_decisions),
            review_status=review_status,
            verification_count=len(self._verification_evidence(run_dir)),
        )
        return ActiveGoalMemory(self.root).write_from_run(
            goal_spec=goal_spec,
            task_plan=task_plan,
            run_status=run,
            review_status=review_status,
            completion=resolved_completion,
            steps=steps or [],
            artifacts=self._artifact_paths(run_dir),
            blockers=blockers
            or self._report_blockers(
                blocked_tasks,
                pending_decisions,
                self._latest_acceptance_report(),
            ),
            risks=risks or [],
            next_actions=next_actions or [],
            pending_decisions=pending_decisions,
            accepted_decisions=accepted_decisions,
            updated_by=updated_by,
            update_reason=update_reason,
        )

    def _task_plan_eval(self, run_dir: Path) -> dict | None:
        path = run_dir / "task_plan_eval.json"
        if not path.exists():
            return None
        return self.store.read(path, "task_plan_eval")

    def _task_plan_quality_summary(self, task_plan_eval: dict | None) -> str:
        if not task_plan_eval:
            return "unknown"
        return (
            f"{task_plan_eval['status']} "
            f"({float(task_plan_eval['overall_score']):.2f}; "
            f"{len(task_plan_eval.get('issues', []))} issue(s))"
        )

    def _pending_decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return [
            decision
            for decision in self.jsonl.read_all(path, "decision_point")
            if decision["status"] == "pending"
        ]

    def _accepted_decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return [
            decision
            for decision in self.jsonl.read_all(path, "decision_point")
            if decision["status"] in {"resolved", "defaulted"}
        ]

    def _decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return self.jsonl.read_all(path, "decision_point")

    def _artifact_paths(self, run_dir: Path) -> list[str]:
        artifact_log = run_dir / "artifacts.jsonl"
        if artifact_log.exists():
            return [
                f"{artifact['path']} - {artifact['summary']}"
                for artifact in self.jsonl.read_all(artifact_log, "artifact")
            ][-20:]
        path = run_dir / "tool_calls.jsonl"
        if not path.exists():
            return []
        artifacts: list[str] = []
        for call in self.jsonl.read_all(path, "tool_call"):
            if call["status"] != "success" or call["tool_name"] not in {
                "write_file",
                "apply_patch",
            }:
                continue
            summary = call["output_summary"]
            if summary not in artifacts:
                artifacts.append(summary)
        return artifacts[-20:]

    def _workspace_envelope(self, run_dir: Path) -> dict:
        path = run_dir / "workspace_envelope.json"
        if not path.exists():
            return {}
        return self.store.read(path, "workspace_envelope")

    def _output_locations(self, workspace_envelope: dict) -> dict:
        return {
            "workspace_root": workspace_envelope.get("workspace_root"),
            "input_roots": workspace_envelope.get("input_roots") or [],
            "output_root": workspace_envelope.get("output_root"),
            "artifact_root": workspace_envelope.get("artifact_root"),
            "worktree_policy": workspace_envelope.get("worktree_policy")
            or workspace_envelope.get("candidate_workspace_policy"),
        }

    def _execution_evidence(self, run_dir: Path) -> list[dict]:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            return []
        relative = path.relative_to(self.root).as_posix()
        items = []
        for evidence in self.jsonl.read_all(path, "task_execution_evidence"):
            candidate = evidence.get("candidate") or {}
            items.append(
                {
                    "task_id": evidence["task_id"],
                    "status": evidence["status"],
                    "summary": evidence["summary"],
                    "failure_type": evidence.get("failure_type") or "none",
                    "candidate_strategy": candidate.get("strategy") or "unknown",
                    "promoted_files": ", ".join(candidate.get("promoted_files", []) or [])
                    or "none",
                    "evidence_path": relative,
                }
            )
        return items

    def _latest_model_selection(self, run_dir: Path) -> dict:
        path = run_dir / "task_execution_evidence.jsonl"
        if path.exists():
            for evidence in reversed(self.jsonl.read_all(path, "task_execution_evidence")):
                selection = (evidence.get("action") or {}).get("model_selection")
                if isinstance(selection, dict) and selection:
                    return selection
        eval_path = run_dir / "eval_report.json"
        if eval_path.exists():
            report = self.store.read(eval_path, "eval_report")
            selection = (report.get("trajectory_eval") or {}).get("model_selection")
            if isinstance(selection, dict) and selection:
                return selection
        return {}

    def _model_route_timeline(self, run_dir: Path, *, limit: int | None = 20) -> list[dict]:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            return []
        timeline = []
        for evidence in self.jsonl.read_all(path, "task_execution_evidence"):
            selection = (evidence.get("action") or {}).get("model_selection")
            if not isinstance(selection, dict) or not selection:
                continue
            timeline.append(
                {
                    "task_id": evidence.get("task_id"),
                    "purpose": selection.get("purpose"),
                    "task_kind": selection.get("task_kind"),
                    "selected_tier": selection.get("selected_tier"),
                    "default_tier": selection.get("default_tier"),
                    "strategy_tier": selection.get("strategy_tier"),
                    "strategy": selection.get("strategy"),
                    "reason": selection.get("reason"),
                    "tier_pressure": selection.get("tier_pressure") or {},
                    "capability_feedback": selection.get("capability_feedback") or {},
                    "evidence_path": path.relative_to(self.root).as_posix(),
                    "created_at": evidence.get("created_at"),
                }
            )
        if limit is None:
            return timeline
        return timeline[-limit:]

    def _model_selection_report_lines(self, model_selection: dict) -> list[str]:
        if not model_selection:
            return ["- No model selection recorded for accepted artifacts."]
        lines = [
            f"- Purpose: {model_selection.get('purpose', 'unknown')}",
            f"- Selected tier: {model_selection.get('selected_tier', 'unknown')}",
            f"- Reason: {model_selection.get('reason', 'No reason recorded.')}",
        ]
        pressure = model_selection.get("tier_pressure") or {}
        if pressure:
            lines.append(
                "- Tier pressure: "
                f"{pressure.get('default_tier', 'unknown')} -> "
                f"{pressure.get('selected_tier', 'unknown')} "
                f"direction={pressure.get('direction', 'unknown')} "
                f"delta={pressure.get('delta', 0)}"
            )
        feedback = model_selection.get("capability_feedback") or {}
        if feedback:
            lines.append(
                "- Capability feedback: "
                f"{feedback.get('status', 'unknown')} "
                f"decision={feedback.get('decision', 'unknown')} "
                f"blocking={feedback.get('blocking_count', 0)} "
                f"review={feedback.get('review_count', 0)}"
            )
            lines.append(f"- Active next step: {capability_feedback_active_next_step(feedback)}")
        return lines

    def _latest_observation_plan(self, run_dir: Path) -> dict:
        path = run_dir / "observation_plans.jsonl"
        if not path.exists():
            return {}
        plans = self.jsonl.read_all(path, "observation_plan")
        return plans[-1] if plans else {}

    def _verification_evidence(self, run_dir: Path) -> list[dict]:
        path = run_dir / "tool_calls.jsonl"
        if not path.exists():
            return []
        return [
            call
            for call in self.jsonl.read_all(path, "tool_call")
            if call.get("tool_name") in {"run_tests", "run_command"}
        ]

    def _latest_acceptance_report(self) -> dict:
        path = self.root / ".asteria" / "acceptance" / "acceptance_report.json"
        if not path.exists():
            return {}
        return self.store.read(path, "acceptance_report")

    def _completion_state(
        self,
        *,
        done: int,
        total: int,
        blocked: int,
        pending_decisions: int,
        review_status: str,
        verification_count: int = 0,
    ) -> str:
        if pending_decisions:
            return "paused_for_decision"
        if blocked:
            return "blocked"
        if total and done == total and review_status == "pass":
            if verification_count == 0:
                return "implemented_unverified"
            return "complete"
        if total and done == total:
            return "implemented_needs_review"
        return "in_progress"

    def _report_workflow_state(self, run: dict) -> str | None:
        phase = str(run.get("current_phase") or "").upper()
        status = str(run.get("status") or "").lower()
        if phase == "ACCEPTED" and status == "completed":
            return "accepted"
        if phase == "ACCEPT" and status == "blocked":
            return "acceptance_blocked"
        return None

    def _display_completion_state(
        self,
        *,
        completion: str,
        review_status: str,
        workflow_state: str | None,
        validation_conclusion: dict,
    ) -> str:
        if workflow_state == "accepted":
            return "accepted"
        if workflow_state == "acceptance_blocked":
            return "acceptance_blocked"
        if (
            completion == "implemented_unverified"
            and review_status == "pass"
            and validation_conclusion.get("status") == "passed"
            and int(validation_conclusion.get("validation_result_count") or 0) > 0
        ):
            return "reviewed_validated"
        return completion

    def _acceptance_summary(self, acceptance: dict) -> str:
        if not acceptance:
            return "not_run"
        raw_aggregate = acceptance.get("aggregate")
        aggregate: dict = raw_aggregate if isinstance(raw_aggregate, dict) else {}
        passed = int(aggregate.get("passed") or 0)
        total = int(aggregate.get("total") or len(acceptance.get("scenarios", [])))
        if acceptance.get("ok"):
            status = "pass"
        elif acceptance.get("repair_closure", {}).get("rerun_ok") is True:
            status = "conditional_after_repair"
        else:
            status = "fail"
        return f"{status} suite={acceptance.get('suite')} scenarios={passed}/{total}"

    def _report_blockers(
        self,
        blocked_tasks: list[dict],
        pending_decisions: list[dict],
        acceptance: dict,
    ) -> list[str]:
        blockers: list[str] = []
        blockers.extend(
            f"Decision {decision['decision_id']} is pending: {decision['question']}"
            for decision in pending_decisions[:3]
        )
        blockers.extend(
            f"Task {task['task_id']} is blocked: {task['title']}" for task in blocked_tasks[:3]
        )
        if acceptance and not acceptance.get("ok"):
            failed = [
                str(item.get("scenario") or "unknown")
                for item in acceptance.get("scenarios", [])
                if isinstance(item, dict) and not item.get("ok")
            ]
            if failed:
                blockers.append("Acceptance failures remain: " + ", ".join(failed[:5]))
        return blockers

    def _report_risks(
        self,
        cost_report: dict,
        task_plan_eval: dict | None,
        execution_evidence: list[dict],
        acceptance: dict,
        verification_evidence: list[dict] | None = None,
        validation_conclusion: dict | None = None,
    ) -> list[str]:
        risks = []
        if task_plan_eval and task_plan_eval.get("status") in {"warn", "fail"}:
            risks.append(self._task_plan_quality_summary(task_plan_eval))
        if cost_report.get("status") in {"near_limit", "exceeded", "stopped"}:
            risks.append(f"Cost status is {cost_report['status']}")
        failed_evidence = [
            item for item in execution_evidence if item["status"] in {"blocked", "failed"}
        ]
        if failed_evidence:
            risks.append(f"{len(failed_evidence)} execution evidence item(s) still need repair")
        if acceptance.get("trend_warnings"):
            risks.extend(str(item) for item in acceptance.get("trend_warnings", [])[:3])
        validation_status = str((validation_conclusion or {}).get("status") or "")
        if (
            verification_evidence is not None
            and len(verification_evidence) == 0
            and validation_status != "passed"
        ):
            risks.append(
                "No verification commands (run_tests/run_command) were recorded — "
                "completion status cannot be confirmed by evidence."
            )
        return list(dict.fromkeys(risks))

    def _final_next_actions(
        self,
        completion: str,
        blockers: list[str],
        risks: list[str],
        acceptance: dict,
    ) -> list[str]:
        if blockers:
            return [
                "Resolve the listed blockers before widening scope.",
                "Run `asteria /debug` or `asteria /replan` against the latest evidence.",
            ]
        if completion in {"complete", "implemented_needs_review"} and not acceptance:
            return ["Run `asteria /acceptance --suite core` before release."]
        if acceptance and not acceptance.get("ok"):
            return [
                "Run `asteria /acceptance --promote-failures --run-promoted --rerun-promoted`.",
                "Re-run `asteria /acceptance-gate` after repair closure.",
            ]
        if risks:
            return ["Review risks, then run `asteria /acceptance-gate` before release."]
        return ["Run `asteria /acceptance-gate --suite core --min-scenarios 6` before release."]

    def _blocked_route_from_observation_plan(self, run_id: str) -> str | None:
        plan = self._latest_observation_plan(self.root / ".asteria" / "runs" / run_id)
        if not plan:
            return None
        return str(plan.get("recommended_route") or recommended_route_from_observation_plan(plan))
