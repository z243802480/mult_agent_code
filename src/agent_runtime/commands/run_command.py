from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.replan_command import ReplanCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.commands.review_command import ReviewCommand
from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


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
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> RunResult:
        if not (self.root / ".agent").exists():
            InitCommand(self.root).run()
        if self.goal and self.run_id:
            raise ValueError("Pass either a new goal or an existing session id, not both.")
        if not self.goal:
            run_store = RunStore(self.root / ".agent", self.validator)
            run_id = self.run_id or run_store.current_session_id()
            if not run_id:
                raise RuntimeError('No current session found. Run `agent new "goal"` first.')
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

        return self.continue_run(plan.run_id, steps)

    def continue_run(
        self,
        run_id: str,
        steps: list[RunStepSummary] | None = None,
    ) -> RunResult:
        steps = steps or []
        if self._task_plan_quality_gate(run_id, steps):
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
            self._execute_until_no_ready(run_id, steps, iteration=index + 1)
            if self._run_status(run_id) in {"blocked", "paused"}:
                break

            if self._budget_guard(run_id, steps, f"iteration-{index + 1}-review"):
                break
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
        return RunResult(
            run_id=run_id,
            status=self._run_status(run_id),
            final_report_path=final_report_path,
            steps=steps,
        )

    def _execute_until_no_ready(
        self,
        run_id: str,
        steps: list[RunStepSummary],
        iteration: int,
    ) -> bool:
        progressed = False
        while self._ready_count(run_id) > 0:
            execute = ExecuteCommand(
                self.root,
                run_id=run_id,
                max_tasks=self.max_tasks_per_iteration,
                model_client=self.execute_model_client or self.model_client,
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
            status = self._run_status(run_id)
            if status == "blocked":
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
        eval_path = self.root / ".agent" / "runs" / run_id / "task_plan_eval.json"
        if not eval_path.exists():
            return False
        task_plan_eval = self.store.read(eval_path, "task_plan_eval")
        if task_plan_eval["status"] != "fail":
            return False
        existing = self._task_plan_quality_decisions(run_id)
        if any(
            decision["status"] in {"resolved", "defaulted", "cancelled"} for decision in existing
        ):
            return False
        pending = [decision for decision in existing if decision["status"] == "pending"]
        decision = (
            pending[0]
            if pending
            else self._create_task_plan_quality_decision(
                run_id,
                task_plan_eval,
                eval_path,
            )
        )
        self._pause_run_for_task_plan_quality(
            run_id,
            f"Task plan quality gate paused before execution: {decision['decision_id']}.",
        )
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

    def _task_plan_quality_decisions(self, run_id: str) -> list[dict]:
        run_dir = self.root / ".agent" / "runs" / run_id
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
                "issue_codes": [
                    str(issue.get("code"))
                    for issue in task_plan_eval.get("issues", [])[:10]
                    if isinstance(issue, dict)
                ],
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
        run_store = RunStore(self.root / ".agent", self.validator)
        run = run_store.load_run(run_id)
        run["status"] = "paused"
        run["current_phase"] = "DECISION"
        run["summary"] = summary
        run_store.update_run(run)

    def _ready_count(self, run_id: str) -> int:
        task_plan = self.store.read(
            self.root / ".agent" / "runs" / run_id / "task_plan.json",
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
        if not (self.root / ".agent" / "policies.json").exists():
            return 8
        policy = self._policy()
        return int(policy["budgets"]["max_iterations_per_goal"])

    def _policy_replans_per_task(self) -> int:
        if not (self.root / ".agent" / "policies.json").exists():
            return 2
        policy = self._policy()
        return int(policy["budgets"].get("max_replans_per_task", 2))

    def _policy(self) -> dict:
        return self.store.read(self.root / ".agent" / "policies.json", "policy_config")

    def _cost_report(self, run_id: str) -> dict:
        path = self.root / ".agent" / "runs" / run_id / "cost_report.json"
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
        run_dir = self.root / ".agent" / "runs" / run_id
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
        run_store = RunStore(self.root / ".agent", self.validator)
        run = run_store.load_run(run_id)
        run["status"] = "paused"
        run["current_phase"] = "DECISION"
        run["summary"] = summary
        run_store.update_run(run)

    def _run_status(self, run_id: str) -> str:
        run = RunStore(self.root / ".agent", self.validator).load_run(run_id)
        return run["status"]

    def _task_counts(self, run_id: str) -> dict[str, int]:
        task_plan = self.store.read(
            self.root / ".agent" / "runs" / run_id / "task_plan.json",
            "task_board",
        )
        counts: dict[str, int] = {}
        for task in task_plan["tasks"]:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        return counts

    def _latest_review_status(self, run_id: str) -> str:
        path = self.root / ".agent" / "runs" / run_id / "eval_report.json"
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
        run_dir = self.root / ".agent" / "runs" / run_id
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        task_plan = self.store.read(run_dir / "task_plan.json", "task_board")
        cost_report = self.store.read(run_dir / "cost_report.json", "cost_report")
        task_plan_eval = self._task_plan_eval(run_dir)
        done = len([task for task in task_plan["tasks"] if task["status"] == "done"])
        blocked_tasks = [task for task in task_plan["tasks"] if task["status"] == "blocked"]
        pending_decisions = self._pending_decisions(run_dir)
        accepted_decisions = self._accepted_decisions(run_dir)
        artifacts = self._artifact_paths(run_dir)
        lines = [
            "# Final Report",
            "",
            f"- Run: {run_id}",
            f"- Goal: {goal_spec['normalized_goal']}",
            f"- Review status: {review_status}",
            f"- Task plan quality: {self._task_plan_quality_summary(task_plan_eval)}",
            f"- Tasks done: {done}/{len(task_plan['tasks'])}",
            f"- Blocked tasks: {len(blocked_tasks)}",
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
                "- Review `review_report.md` before trusting the result for production use.",
                "- Resolve pending decisions with `agent decide` if the run is paused.",
                "- Continue with `agent debug` if any task remains blocked.",
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
