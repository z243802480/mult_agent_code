from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.agents.debug_agent import DebugAgent
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.defaults import create_default_tool_registry
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class RepairSummary:
    task_id: str
    status: str
    summary: str
    repair_calls: int
    verification_calls: int


@dataclass(frozen=True)
class DebugResult:
    run_id: str
    repaired: int
    still_blocked: int
    repairs: list[RepairSummary] = field(default_factory=list)
    cost_report_path: Path | None = None

    def to_text(self) -> str:
        lines = [
            f"Debugged run: {self.run_id}",
            f"Repaired tasks: {self.repaired}",
            f"Still blocked: {self.still_blocked}",
        ]
        for repair in self.repairs:
            lines.append(
                f"- {repair.task_id}: {repair.status} ({repair.repair_calls} repair, {repair.verification_calls} verification)"
            )
        if self.cost_report_path:
            lines.append(f"Cost report: {self.cost_report_path}")
        return "\n".join(lines)


class DebugCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        task_id: str | None = None,
        max_repairs: int = 1,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.task_id = task_id
        self.max_repairs = max_repairs
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.registry = create_default_tool_registry()

    def run(self) -> DebugResult:
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
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(policy, self._read_cost(cost_report_path, run_id), run_id=run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        context = RuntimeContext(
            root=self.root,
            run_id=run_id,
            policy=policy,
            validator=self.validator,
            event_logger=event_logger,
            budget=budget,
        )
        debug_agent = DebugAgent(self._model_client(run_dir, budget), self.validator)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)

        run["status"] = "running"
        run["current_phase"] = "DEBUG"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "DebugCommand", "EXECUTE -> DEBUG")

        repairs: list[RepairSummary] = []
        for task in self._blocked_tasks(task_board)[: self.max_repairs]:
            repairs.append(self._repair_task(task, task_board, context, debug_agent, goal_spec, run_dir))
            task_board.promote_unblocked()

        self._mirror_backlog(agent_dir, task_board)
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")

        repaired = len([item for item in repairs if item.status == "done"])
        still_blocked = len([item for item in repairs if item.status == "blocked"])
        all_tasks = task_board.list_tasks()
        if all(task["status"] == "done" for task in all_tasks):
            run["status"] = "completed"
            run["current_phase"] = "DONE"
            run["ended_at"] = now_iso()
            run["summary"] = "Debug repaired all planned tasks."
            event_logger.record(run_id, "run_completed", "DebugCommand", run["summary"])
        elif still_blocked:
            run["status"] = "blocked"
            run["summary"] = "Debug attempted repair but work remains blocked."
            event_logger.record(run_id, "run_blocked", "DebugCommand", run["summary"])
        else:
            run["status"] = "running"
            run["summary"] = f"Debug repaired {repaired} task(s); more work remains."
        run_store.update_run(run)

        return DebugResult(
            run_id=run_id,
            repaired=repaired,
            still_blocked=still_blocked,
            repairs=repairs,
            cost_report_path=cost_report_path,
        )

    def _repair_task(
        self,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        debug_agent: DebugAgent,
        goal_spec: dict,
        run_dir: Path,
    ) -> RepairSummary:
        task_id = task["task_id"]
        context.event_logger.record(context.run_id, "repair_started", "DebugCommand", f"Started repair for {task_id}")
        try:
            if context.budget:
                context.budget.record_repair_attempt()
            task_board.update_status(task_id, "ready")
            task_board.update_status(task_id, "in_progress")
            action = debug_agent.propose_repair(
                task=task_board.get_task(task_id),
                goal_spec=goal_spec,
                failure_evidence=self._failure_evidence(run_dir, task_id),
                available_tools=self.registry.names(),
                run_id=context.run_id or "",
            )
            self._run_tool_calls(action["tool_calls"], task, context)
            task_board.update_status(task_id, "testing")
            verification = self._run_tool_calls(action["verification"], task, context)
            if all(result.ok for result in verification):
                task_board.update_status(task_id, "reviewing")
                task_board.update_status(task_id, "done")
                task_board.update_notes(task_id, action.get("completion_notes") or action["summary"])
                context.event_logger.record(context.run_id, "repair_completed", "DebugCommand", f"Repaired {task_id}")
                return RepairSummary(task_id, "done", action["summary"], len(action["tool_calls"]), len(action["verification"]))
            self._block_task(task_board, task_id, "Repair verification failed.", context)
            return RepairSummary(task_id, "blocked", "Repair verification failed", len(action["tool_calls"]), len(action["verification"]))
        except Exception as exc:  # noqa: BLE001 - repair loop must persist failures
            self._block_task(task_board, task_id, str(exc), context)
            return RepairSummary(task_id, "blocked", str(exc), 0, 0)

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
                agent_id="DebugAgent",
                **call["args"],
            )
            results.append(result)
            if not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
        return results

    def _failure_evidence(self, run_dir: Path, task_id: str) -> dict:
        tool_calls = self._read_jsonl(run_dir / "tool_calls.jsonl", "tool_call")
        model_calls = self._read_jsonl(run_dir / "model_calls.jsonl", "model_call")
        events = self._read_jsonl(run_dir / "events.jsonl", "event")
        return {
            "task_id": task_id,
            "recent_tool_failures": [
                call for call in tool_calls if call.get("task_id") == task_id and call.get("status") != "success"
            ][-10:],
            "recent_model_failures": [
                call for call in model_calls if call.get("status") != "success"
            ][-5:],
            "recent_events": [
                event for event in events if event.get("type") in {"task_blocked", "tool_called", "run_blocked"}
            ][-20:],
        }

    def _blocked_tasks(self, task_board: TaskBoard) -> list[dict]:
        tasks = task_board.list_tasks()
        if self.task_id:
            task = task_board.get_task(self.task_id)
            return [task] if task["status"] == "blocked" else []
        return [task for task in tasks if task["status"] == "blocked"]

    def _block_task(self, task_board: TaskBoard, task_id: str, reason: str, context: RuntimeContext) -> None:
        try:
            current = task_board.get_task(task_id)
            if current["status"] not in {"blocked", "done", "discarded"}:
                task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, reason)
        except TaskStateError:
            pass
        if context.event_logger:
            context.event_logger.record(context.run_id, "repair_blocked", "DebugCommand", reason)

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

    def _mirror_backlog(self, agent_dir: Path, task_board: TaskBoard) -> None:
        self.store.write(
            agent_dir / "tasks" / "backlog.json",
            {"schema_version": "0.1.0", "tasks": task_board.list_tasks()},
            "task_board",
        )

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted([path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name)
        return runs[-1].name if runs else None
