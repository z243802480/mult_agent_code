from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from agent_runtime.agents.coder_agent import CoderAgent
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.defaults import create_default_tool_registry
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class TaskExecutionSummary:
    task_id: str
    status: str
    summary: str
    tool_calls: int
    verification_calls: int


@dataclass(frozen=True)
class ExecuteResult:
    run_id: str
    completed: int
    blocked: int
    executed_tasks: list[TaskExecutionSummary] = field(default_factory=list)
    cost_report_path: Path | None = None

    def to_text(self) -> str:
        lines = [
            f"Executed run: {self.run_id}",
            f"Completed tasks: {self.completed}",
            f"Blocked tasks: {self.blocked}",
        ]
        for task in self.executed_tasks:
            lines.append(
                f"- {task.task_id}: {task.status} ({task.tool_calls} tool, {task.verification_calls} verification)"
            )
        if self.cost_report_path:
            lines.append(f"Cost report: {self.cost_report_path}")
        return "\n".join(lines)


class ExecuteCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        max_tasks: int = 1,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.max_tasks = max_tasks
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.registry = create_default_tool_registry()

    def run(self) -> ExecuteResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `agent plan` first.")
        run_dir = run_store.run_dir(run_id)
        run = run_store.load_run(run_id)
        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        project_config = self.store.read(agent_dir / "project.json", "project_config")
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        cost_report_path = run_dir / "cost_report.json"
        existing_cost = self._read_cost(cost_report_path, run_id)
        budget = BudgetController.from_report(policy, existing_cost, run_id=run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        context = RuntimeContext(
            root=self.root,
            run_id=run_id,
            policy=policy,
            validator=self.validator,
            event_logger=event_logger,
            budget=budget,
        )
        model_client = self._model_client(run_dir, budget)
        coder = CoderAgent(model_client, self.validator)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)

        run["status"] = "running"
        run["current_phase"] = "EXECUTE"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ExecuteCommand", "PLAN -> EXECUTE")

        executed: list[TaskExecutionSummary] = []
        for task in task_board.ready_tasks()[: self.max_tasks]:
            executed.append(
                self._execute_task(
                    task=task,
                    task_board=task_board,
                    context=context,
                    coder=coder,
                    goal_spec=goal_spec,
                    project_config=project_config,
                )
            )
            task_board.promote_unblocked()

        self._mirror_backlog(agent_dir, task_board)
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")

        completed = len([item for item in executed if item.status == "done"])
        blocked = len([item for item in executed if item.status == "blocked"])
        remaining_ready = task_board.ready_tasks()
        all_tasks = task_board.list_tasks()
        if all(task["status"] == "done" for task in all_tasks):
            run["status"] = "completed"
            run["current_phase"] = "DONE"
            run["ended_at"] = now_iso()
            run["summary"] = "Execution completed all planned tasks."
            event_logger.record(run_id, "run_completed", "ExecuteCommand", run["summary"])
        elif blocked and not remaining_ready:
            run["status"] = "blocked"
            run["summary"] = "Execution blocked; repair or user decision is required."
            event_logger.record(run_id, "run_blocked", "ExecuteCommand", run["summary"])
        else:
            run["status"] = "running"
            run["summary"] = f"Executed {len(executed)} task(s); more work remains."
        run_store.update_run(run)

        return ExecuteResult(
            run_id=run_id,
            completed=completed,
            blocked=blocked,
            executed_tasks=executed,
            cost_report_path=cost_report_path,
        )

    def _execute_task(
        self,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
    ) -> TaskExecutionSummary:
        task_id = task["task_id"]
        if context.event_logger:
            context.event_logger.record(context.run_id, "task_started", "ExecuteCommand", f"Started {task_id}")
        task_board.update_status(task_id, "in_progress")
        try:
            action = coder.propose_action(
                task=task,
                goal_spec=goal_spec,
                project_config=project_config,
                available_tools=self.registry.names(),
                run_id=context.run_id or "",
            )
            self._run_tool_calls(action["tool_calls"], task, context)
            task_board.update_status(task_id, "testing")
            verification_results = self._run_tool_calls(action["verification"], task, context)
            if all(result.ok for result in verification_results):
                task_board.update_status(task_id, "reviewing")
                task_board.update_status(task_id, "done")
                task_board.update_notes(task_id, action.get("completion_notes") or action["summary"])
                if context.event_logger:
                    context.event_logger.record(context.run_id, "task_completed", "ExecuteCommand", f"Completed {task_id}")
                return TaskExecutionSummary(
                    task_id=task_id,
                    status="done",
                    summary=action["summary"],
                    tool_calls=len(action["tool_calls"]),
                    verification_calls=len(action["verification"]),
                )
            task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, "Verification failed; repair is required.")
            if context.event_logger:
                context.event_logger.record(context.run_id, "task_blocked", "ExecuteCommand", f"Blocked {task_id}")
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary="Verification failed",
                tool_calls=len(action["tool_calls"]),
                verification_calls=len(action["verification"]),
            )
        except Exception as exc:  # noqa: BLE001 - execution loop must persist failures
            self._block_task(task_board, task_id, str(exc), context)
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary=str(exc),
                tool_calls=0,
                verification_calls=0,
            )

    def _run_tool_calls(self, calls: list[dict], task: dict, context: RuntimeContext) -> list:
        results = []
        allowed = set(task["allowed_tools"])
        for call in calls:
            tool_name = call["tool_name"]
            if tool_name not in allowed:
                raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
            result = self.registry.call(
                tool_name,
                context,
                task_id=task["task_id"],
                agent_id="CoderAgent",
                **call["args"],
            )
            results.append(result)
            if not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
        return results

    def _block_task(self, task_board: TaskBoard, task_id: str, reason: str, context: RuntimeContext) -> None:
        try:
            current = task_board.get_task(task_id)
            if current["status"] not in {"blocked", "done", "discarded"}:
                task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, reason)
        except TaskStateError:
            pass
        if context.event_logger:
            context.event_logger.record(context.run_id, "task_blocked", "ExecuteCommand", reason)

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
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }

    def _mirror_backlog(self, agent_dir: Path, task_board: TaskBoard) -> None:
        self.store.write(agent_dir / "tasks" / "backlog.json", {"schema_version": "0.1.0", "tasks": task_board.list_tasks()}, "task_board")

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted([path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name)
        return runs[-1].name if runs else None
