from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.commands.review_command import ReviewCommand
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
        goal: str,
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
        max_iterations = self.max_iterations or self._policy_iterations()
        for index in range(max_iterations):
            self._execute_until_no_ready(run_id, steps, iteration=index + 1)
            if self._run_status(run_id) in {"blocked", "paused"}:
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
                        (
                            f"{debug.repaired} repaired, "
                            f"{debug.still_blocked} still blocked."
                        ),
                    )
                )
                if self._run_status(run_id) == "blocked":
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
        policy_path = self.root / ".agent" / "policies.json"
        if not policy_path.exists():
            return 8
        policy = self.store.read(policy_path, "policy_config")
        return int(policy["budgets"]["max_iterations_per_goal"])

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

    def _artifact_paths(self, run_dir: Path) -> list[str]:
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
