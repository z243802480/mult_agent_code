from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.agents.review_agent import ReviewAgent
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
class ReviewResult:
    run_id: str
    status: str
    score: float
    eval_report_path: Path
    review_report_path: Path
    cost_report_path: Path

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Reviewed run: {self.run_id}",
                f"Status: {self.status}",
                f"Score: {self.score:.2f}",
                f"Eval report: {self.eval_report_path}",
                f"Review report: {self.review_report_path}",
                f"Cost report: {self.cost_report_path}",
            ]
        )


class ReviewCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> ReviewResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or self._latest_run_id(agent_dir)
        if not run_id:
            raise RuntimeError("No run found. Run `agent plan` first.")
        run_dir = run_store.run_dir(run_id)
        run = run_store.load_run(run_id)
        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(policy, self._read_cost(cost_report_path, run_id), run_id=run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        reviewer = ReviewAgent(self._model_client(run_dir, budget), self.validator)

        run["status"] = "running"
        run["current_phase"] = "REVIEW"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ReviewCommand", "DONE -> REVIEW")

        review_context = self._review_context(agent_dir, run_dir, run_id)
        eval_report = reviewer.evaluate(review_context, run_id)
        eval_report_path = run_dir / "eval_report.json"
        self.store.write(eval_report_path, eval_report, "eval_report")
        review_report_path = run_dir / "review_report.md"
        review_report_path.write_text(self._markdown_report(eval_report), encoding="utf-8")
        event_logger.record(
            run_id,
            "artifact_created",
            "ReviewAgent",
            f"EvalReport created with status {eval_report['overall']['status']}",
            {"path": "eval_report.json", "score": eval_report["overall"]["score"]},
        )

        self.store.write(cost_report_path, budget.cost_report(), "cost_report")
        status = eval_report["overall"]["status"]
        if status == "pass":
            run["status"] = "completed"
            run["current_phase"] = "REVIEWED"
            run["ended_at"] = now_iso()
        elif status == "partial":
            run["status"] = "running"
            run["current_phase"] = "REVIEWED"
        else:
            run["status"] = "blocked"
            run["current_phase"] = "REVIEWED"
        run["summary"] = eval_report["overall"]["reason"]
        run_store.update_run(run)

        return ReviewResult(
            run_id=run_id,
            status=status,
            score=float(eval_report["overall"]["score"]),
            eval_report_path=eval_report_path,
            review_report_path=review_report_path,
            cost_report_path=cost_report_path,
        )

    def _review_context(self, agent_dir: Path, run_dir: Path, run_id: str) -> dict:
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        task_plan = self.store.read(run_dir / "task_plan.json", "task_board")
        cost_report = self._read_cost(run_dir / "cost_report.json", run_id)
        tool_calls = self._read_jsonl(run_dir / "tool_calls.jsonl", "tool_call")
        model_calls = self._read_jsonl(run_dir / "model_calls.jsonl", "model_call")
        events = self._read_jsonl(run_dir / "events.jsonl", "event")
        return {
            "run_id": run_id,
            "project": self.store.read(agent_dir / "project.json", "project_config"),
            "goal_spec": goal_spec,
            "task_plan": task_plan,
            "cost_report": cost_report,
            "trajectory": {
                "events": events[-50:],
                "tool_calls": tool_calls[-50:],
                "model_calls": model_calls[-20:],
            },
            "deterministic_checks": self._deterministic_checks(task_plan, tool_calls, cost_report),
        }

    def _deterministic_checks(self, task_plan: dict, tool_calls: list[dict], cost_report: dict) -> dict:
        tasks = task_plan.get("tasks", [])
        done = [task for task in tasks if task["status"] == "done"]
        blocked = [task for task in tasks if task["status"] == "blocked"]
        verification_calls = [
            call for call in tool_calls if call["tool_name"] in {"run_tests", "run_command"}
        ]
        passed_verification = [
            call for call in verification_calls if call["status"] == "success"
        ]
        return {
            "task_completion_rate": len(done) / len(tasks) if tasks else 0,
            "blocked_task_count": len(blocked),
            "verification_call_count": len(verification_calls),
            "verification_pass_rate": len(passed_verification) / len(verification_calls) if verification_calls else 0,
            "cost_status": cost_report.get("status", "within_budget"),
        }

    def _markdown_report(self, eval_report: dict) -> str:
        overall = eval_report["overall"]
        return "\n".join(
            [
                "# Review Report",
                "",
                f"- Status: {overall['status']}",
                f"- Score: {overall['score']}",
                f"- Reason: {overall['reason']}",
                "",
                "## Goal Eval",
                "",
                f"```json\n{self._json(eval_report['goal_eval'])}\n```",
                "",
                "## Artifact Eval",
                "",
                f"```json\n{self._json(eval_report['artifact_eval'])}\n```",
                "",
                "## Outcome Eval",
                "",
                f"```json\n{self._json(eval_report['outcome_eval'])}\n```",
                "",
                "## Trajectory Eval",
                "",
                f"```json\n{self._json(eval_report['trajectory_eval'])}\n```",
                "",
                "## Cost Eval",
                "",
                f"```json\n{self._json(eval_report['cost_eval'])}\n```",
                "",
            ]
        )

    def _json(self, value: dict) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)

    def _model_client(self, run_dir: Path, budget: BudgetController) -> ModelClient:
        if self.model_client:
            return MeteredModelClient(
                self.model_client,
                budget,
                ModelCallLogger(run_dir, self.validator),
            )
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
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }

    def _read_jsonl(self, path: Path, schema_name: str) -> list[dict]:
        if not path.exists():
            return []
        return self.jsonl.read_all(path, schema_name)

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted([path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name)
        return runs[-1].name if runs else None
