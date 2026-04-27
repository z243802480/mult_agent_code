from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
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
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> RunResult:
        if not (self.root / ".agent").exists():
            InitCommand(self.root).run()

        plan = PlanCommand(
            self.root,
            self.goal,
            model_client=self.plan_model_client or self.model_client,
        ).run()
        steps = [
            RunStepSummary("plan", "completed", f"Created {plan.task_count} task(s)."),
        ]

        run_id = plan.run_id
        max_iterations = self.max_iterations or self._policy_iterations()
        for index in range(max_iterations):
            before_counts = self._task_counts(run_id)
            execute = ExecuteCommand(
                self.root,
                run_id=run_id,
                max_tasks=self.max_tasks_per_iteration,
                model_client=self.execute_model_client or self.model_client,
            ).run()
            steps.append(
                RunStepSummary(
                    "execute",
                    "completed",
                    (
                        f"Iteration {index + 1}: {execute.completed} completed, "
                        f"{execute.blocked} blocked."
                    ),
                )
            )
            status = self._run_status(run_id)
            if status == "completed":
                break
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
                    break
            after_counts = self._task_counts(run_id)
            if before_counts == after_counts and execute.completed == 0 and execute.blocked == 0:
                steps.append(
                    RunStepSummary(
                        "execute",
                        "stopped",
                        "No ready task made progress; stopping the run loop.",
                    )
                )
                break

        review = ReviewCommand(
            self.root,
            run_id=run_id,
            model_client=self.review_model_client or self.model_client,
        ).run()
        steps.append(RunStepSummary("review", review.status, f"Score {review.score:.2f}."))

        compact = CompactCommand(self.root, run_id=run_id, focus="final run handoff").run()
        steps.append(
            RunStepSummary("compact", "completed", f"Snapshot: {compact.snapshot_path.name}.")
        )

        final_report_path = self._write_final_report(run_id, review.status, steps)
        return RunResult(
            run_id=run_id,
            status=self._run_status(run_id),
            final_report_path=final_report_path,
            steps=steps,
        )

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
        lines.extend(
            [
                "",
                "## Next Actions",
                "",
                "- Review `review_report.md` before trusting the result for production use.",
                "- Continue with `agent debug` if any task remains blocked.",
            ]
        )
        path = run_dir / "final_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _artifact_paths(self, run_dir: Path) -> list[str]:
        path = run_dir / "tool_calls.jsonl"
        if not path.exists():
            return []
        artifacts: list[str] = []
        for call in self.jsonl.read_all(path, "tool_call"):
            if call["status"] != "success" or call["tool_name"] not in {"write_file", "apply_patch"}:
                continue
            summary = call["output_summary"]
            if summary not in artifacts:
                artifacts.append(summary)
        return artifacts[-20:]
