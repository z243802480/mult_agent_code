from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.compact_command import CompactCommand
from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.commands.research_command import ResearchCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.base import ModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


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
    steps: list[RunStepSummary] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            f"Run: {self.run_id}",
            f"Status: {self.status}",
            f"Final report: {self.final_report_path}",
        ]
        for step in self.steps:
            lines.append(f"- {step.name}: {step.status} - {step.summary}")
        return "\n".join(lines)


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

        if self._ready_count(run_id) > 0 and self._task_plan_quality_gate(run_id, steps):
            compact = CompactCommand(self.root, run_id=run_id, focus="task plan quality gate").run()
            steps.append(
                RunStepSummary("compact", "completed", f"Snapshot: {compact.snapshot_path.name}.")
            )
            final_report_path = self._write_final_report(
                run_id,
                self._latest_review_status(run_id),
                steps,
            )
            return RunResult(
                run_id=run_id,
                status=self._run_status(run_id),
                final_report_path=final_report_path,
                steps=steps,
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
                model_client=self.review_model_client or self.model_client,
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
            if review.decision_count:
                break
            if review.status == "pass" or review.follow_up_count == 0:
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
            summary=(
                f"Run {run_id} 已完成，状态：{run_status}。"
                f"共 {len(steps)} 个执行步骤。"
            ),
            artifact_refs=[str(final_report_path)],
        )
        return RunResult(
            run_id=run_id,
            status=run_status,
            final_report_path=final_report_path,
            steps=steps,
        )

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
            return True
        decision = self._create_budget_decision(run_id, pressure, phase)
        self._pause_run_for_budget(
            run_id,
            f"Budget guard paused before {phase}: {decision['decision_id']}.",
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
        agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
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

    def _run_status(self, run_id: str) -> str:
        run = RunStore(self.root / ".asteria", self.validator).load_run(run_id)
        return run["status"]

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
        promotion_summary = CandidatePromotionQueue(self.validator).summary(run_dir)
        acceptance = self._latest_acceptance_report()
        completion = self._completion_state(
            done=done,
            total=len(task_plan["tasks"]),
            blocked=len(blocked_tasks),
            pending_decisions=len(pending_decisions),
            review_status=review_status,
        )
        blockers = self._report_blockers(blocked_tasks, pending_decisions, acceptance)
        risks = self._report_risks(cost_report, task_plan_eval, execution_evidence, acceptance)
        next_actions = self._final_next_actions(completion, blockers, risks, acceptance)
        lines = [
            "# Final Report",
            "",
            "## Current State",
            "",
            f"- Run: {run_id}",
            f"- Goal: {goal_spec['normalized_goal']}",
            f"- Completion: {completion}",
            f"- Review status: {review_status}",
            f"- Task plan quality: {self._task_plan_quality_summary(task_plan_eval)}",
            f"- Tasks done: {done}/{len(task_plan['tasks'])}",
            f"- Blocked tasks: {len(blocked_tasks)}",
            f"- Pending decisions: {len(pending_decisions)}",
            f"- Release gate signal: {self._acceptance_summary(acceptance)}",
            f"- Model calls: {cost_report['model_calls']}",
            f"- Tool calls: {cost_report['tool_calls']}",
            "",
            "## Steps",
            "",
        ]
        lines.extend(f"- {step.name}: {step.status} - {step.summary}" for step in steps)
        if artifacts:
            lines.extend(["", "## Artifacts", ""])
            lines.extend(f"- {path}" for path in artifacts)
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
        return path

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
    ) -> str:
        if pending_decisions:
            return "paused_for_decision"
        if blocked:
            return "blocked"
        if total and done == total and review_status == "pass":
            return "complete"
        if total and done == total:
            return "implemented_needs_review"
        return "in_progress"

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
