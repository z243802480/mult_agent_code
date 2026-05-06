from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from agent_runtime.agents.coder_agent import CoderAgent
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.task_contract import (
    allows_expected_failure,
    check_completion_contract,
)
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.security.shell_guard import ShellGuard, ShellPolicyError
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.jsonl_store import JsonlStore
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
        runtime_context = ContextLoader(self.root, self.validator).load(run_id)

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
                    runtime_context=runtime_context,
                )
            )
            task_board.promote_unblocked()

        self._mirror_backlog(agent_dir, task_board)
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")

        completed = len([item for item in executed if item.status == "done"])
        blocked = len([item for item in executed if item.status == "blocked"])
        remaining_ready = task_board.ready_tasks()
        all_tasks = task_board.list_tasks()
        if self._pending_decisions(run_dir):
            run["status"] = "paused"
            run["current_phase"] = "DECISION"
            run["summary"] = "Execution paused for a user decision."
            event_logger.record(run_id, "run_paused", "ExecuteCommand", run["summary"])
        elif all(task["status"] == "done" for task in all_tasks):
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
        runtime_context: dict,
    ) -> TaskExecutionSummary:
        task_id = task["task_id"]
        if context.event_logger:
            context.event_logger.record(
                context.run_id, "task_started", "ExecuteCommand", f"Started {task_id}"
            )
        task_board.update_status(task_id, "in_progress")
        try:
            action = coder.propose_action(
                task=task,
                goal_spec=goal_spec,
                project_config=project_config,
                available_tools=self.registry.names(),
                run_id=context.run_id or "",
                runtime_context=runtime_context,
            )
            self._require_non_empty_action(action)
            decision = self._create_policy_decision_if_needed(action, task, context)
            if decision is not None:
                task_board.update_status(task_id, "blocked")
                task_board.update_notes(task_id, f"Waiting for decision: {decision['decision_id']}")
                if context.event_logger:
                    context.event_logger.record(
                        context.run_id,
                        "task_paused_for_decision",
                        "ExecuteCommand",
                        f"{task_id} paused for {decision['decision_id']}",
                        {"task_id": task_id, "decision_id": decision["decision_id"]},
                    )
                return TaskExecutionSummary(
                    task_id=task_id,
                    status="blocked",
                    summary=f"Waiting for decision: {decision['decision_id']}",
                    tool_calls=0,
                    verification_calls=0,
                )
            tool_results = self._run_tool_calls(action["tool_calls"], task, context)
            task_board.update_status(task_id, "testing")
            verification_results = self._run_tool_calls(
                action["verification"],
                task,
                context,
                stop_on_failure=False,
            )
            contract_check = check_completion_contract(
                task,
                self._changed_files(tool_results),
                verification_results,
            )
            if contract_check.ok:
                self._record_experiment(
                    context,
                    task,
                    action,
                    tool_results,
                    verification_results,
                    "keep",
                    "Verification passed.",
                    contract_check=contract_check.to_dict(),
                )
                task_board.update_status(task_id, "reviewing")
                task_board.update_status(task_id, "done")
                task_board.update_notes(
                    task_id, action.get("completion_notes") or action["summary"]
                )
                if context.event_logger:
                    context.event_logger.record(
                        context.run_id, "task_completed", "ExecuteCommand", f"Completed {task_id}"
                    )
                return TaskExecutionSummary(
                    task_id=task_id,
                    status="done",
                    summary=action["summary"],
                    tool_calls=len(action["tool_calls"]),
                    verification_calls=len(action["verification"]),
                )
            reason = contract_check.summary()
            self._record_experiment(
                context,
                task,
                action,
                tool_results,
                verification_results,
                "discard",
                reason,
                rollback_results=self._rollback_backups(context, task, tool_results),
                contract_check=contract_check.to_dict(),
            )
            task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, f"{reason}; candidate was rolled back.")
            if context.event_logger:
                context.event_logger.record(
                    context.run_id, "task_blocked", "ExecuteCommand", f"Blocked {task_id}"
                )
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary=reason,
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

    def _require_non_empty_action(self, action: dict) -> None:
        if not action.get("tool_calls") and not action.get("verification"):
            raise RuntimeError("ExecutionAction contained no tool calls or verification.")

    def _accepts_diagnostic_failure(self, task: dict, tool_name: str, result: object) -> bool:
        if tool_name not in {"run_command", "run_tests"}:
            return False
        if getattr(result, "ok", False) or getattr(result, "error", None) != "nonzero_exit":
            return False
        return allows_expected_failure(task)

    def _run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: RuntimeContext,
        stop_on_failure: bool = True,
    ) -> list:
        results = []
        allowed = set(task["allowed_tools"])
        for call in calls:
            tool_name = call["tool_name"]
            if tool_name not in allowed:
                raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
            result = self.registry.call(
                tool_name,
                self._context_with_approval(context, task, tool_name, call["args"]),
                task_id=task["task_id"],
                agent_id="CoderAgent",
                **call["args"],
            )
            if self._accepts_diagnostic_failure(task, tool_name, result):
                result.ok = True
                result.error = None
                result.summary = f"Diagnostic failure accepted: {result.summary}"
            results.append(result)
            if stop_on_failure and not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
        return results

    def _create_policy_decision_if_needed(
        self,
        action: dict,
        task: dict,
        context: RuntimeContext,
    ) -> dict | None:
        for call in [*action.get("tool_calls", []), *action.get("verification", [])]:
            tool_name = call["tool_name"]
            if tool_name not in {"run_command", "run_tests"}:
                continue
            command = str(call.get("args", {}).get("command") or "")
            if not command:
                continue
            denial = self._shell_denial(context.policy, command)
            if denial is None or self._has_execution_approval(
                context, task, tool_name, call["args"]
            ):
                continue
            return self._create_execution_decision(context, task, tool_name, call["args"], denial)
        return None

    def _shell_denial(self, policy: dict, command: str) -> str | None:
        try:
            ShellGuard(policy["permissions"]).validate(command)
        except ShellPolicyError as exc:
            return str(exc)
        return None

    def _create_execution_decision(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
        denial: str,
    ) -> dict:
        assert context.run_id is not None
        assert context.run_dir is not None
        existing = self._matching_decisions(context.run_dir, task, tool_name, args)
        for decision in existing:
            if decision["status"] == "pending":
                return decision
        options = [
            {
                "option_id": "approve_once",
                "label": "Approve once",
                "tradeoff": "Allow this exact command once for this task; keeps global policy unchanged.",
                "action": "record_constraint",
            },
            {
                "option_id": "skip",
                "label": "Keep blocked",
                "tradeoff": "Do not run the command; the task remains blocked until replanned or changed.",
                "action": "record_constraint",
            },
        ]
        result = DecideCommand(
            self.root,
            run_id=context.run_id,
            question=(
                f"Approve one-time execution for task {task['task_id']}? "
                f"Policy blocked `{tool_name}` because: {denial}"
            ),
            options_json=json.dumps(options, ensure_ascii=False),
            recommended_option_id="skip",
            default_option_id="skip",
            impact_json=json.dumps(
                {"scope": "medium", "budget": "low", "risk": "high", "quality": "medium"},
                ensure_ascii=False,
            ),
            metadata={
                "kind": "execution_policy_approval",
                "task_id": task["task_id"],
                "tool_name": tool_name,
                "args_fingerprint": self._args_fingerprint(args),
                "denial": denial,
            },
        ).run()
        return result.decisions[0]

    def _context_with_approval(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> RuntimeContext:
        if tool_name not in {"run_command", "run_tests"}:
            return context
        if not self._has_execution_approval(context, task, tool_name, args):
            return context
        policy = deepcopy(context.policy)
        permissions = policy.setdefault("permissions", {})
        permissions["allow_shell"] = True
        permissions["allow_shell_operators"] = True
        permissions["allow_destructive_shell"] = True
        permissions["allow_remote_push"] = True
        permissions["allow_deploy"] = True
        permissions["allow_global_package_install"] = True
        return RuntimeContext(
            root=context.root,
            run_id=context.run_id,
            policy=policy,
            validator=context.validator,
            event_logger=context.event_logger,
            budget=context.budget,
        )

    def _has_execution_approval(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> bool:
        if context.run_dir is None:
            return False
        for decision in self._matching_decisions(context.run_dir, task, tool_name, args):
            if decision["status"] in {"resolved", "defaulted"}:
                return decision.get("selected_option_id") == "approve_once"
        return False

    def _matching_decisions(
        self,
        run_dir: Path,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        fingerprint = self._args_fingerprint(args)
        matches = []
        for decision in JsonlStore(self.validator).read_all(path, "decision_point"):
            metadata = decision.get("metadata") or {}
            if (
                metadata.get("kind") == "execution_policy_approval"
                and metadata.get("task_id") == task["task_id"]
                and metadata.get("tool_name") == tool_name
                and metadata.get("args_fingerprint") == fingerprint
            ):
                matches.append(decision)
        return matches

    def _args_fingerprint(self, args: dict) -> str:
        return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _record_experiment(
        self,
        context: RuntimeContext,
        task: dict,
        action: dict,
        tool_results: list,
        verification_results: list,
        decision: str,
        reason: str,
        rollback_results: list | None = None,
        contract_check: dict | None = None,
    ) -> None:
        if not context.run_dir:
            return
        if decision == "keep":
            self._record_artifacts(context, task, tool_results)
        path = context.run_dir / "experiments.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "experiment") if path.exists() else []
        backup_ids = [
            result.data["backup_id"]
            for result in tool_results
            if result.ok and isinstance(result.data, dict) and result.data.get("backup_id")
        ]
        changed_files = self._changed_files(tool_results)
        verification_passed = len([result for result in verification_results if result.ok])
        experiment = {
            "schema_version": "0.1.0",
            "experiment_id": f"exp-{len(existing) + 1:04d}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "idea": action["summary"],
            "baseline": {
                "task_status": task["status"],
                "acceptance_count": len(task.get("acceptance", [])),
            },
            "candidate": {
                "changed_files": sorted(set(changed_files)),
                "backup_ids": backup_ids,
                "rollback": self._rollback_summary(rollback_results or []),
            },
            "evaluator": {
                "commands": [
                    call.get("args", {}).get("command") for call in action.get("verification", [])
                ],
                "tool_count": len(action.get("tool_calls", [])),
            },
            "metrics_after": {
                "verification_total": len(verification_results),
                "verification_passed": verification_passed,
                "verification_pass_rate": (
                    verification_passed / len(verification_results) if verification_results else 1.0
                ),
            },
            "contract_check": contract_check or {},
            "decision": decision,
            "reason": reason,
        }
        store.append(path, experiment, "experiment")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "experiment_recorded",
                "ExecuteCommand",
                f"{experiment['experiment_id']} -> {decision}",
                {
                    "experiment_id": experiment["experiment_id"],
                    "task_id": task["task_id"],
                    "decision": decision,
                    "backup_ids": backup_ids,
                },
            )

    def _rollback_backups(
        self,
        context: RuntimeContext,
        task: dict,
        tool_results: list,
    ) -> list:
        backup_ids = [
            result.data["backup_id"]
            for result in tool_results
            if result.ok and isinstance(result.data, dict) and result.data.get("backup_id")
        ]
        rollback_results = []
        for backup_id in reversed(backup_ids):
            result = self.registry.call(
                "restore_backup",
                context,
                task_id=task["task_id"],
                agent_id="ExecuteCommand",
                backup_id=backup_id,
                delete_created_files=False,
            )
            rollback_results.append(result)
        return rollback_results

    def _rollback_summary(self, rollback_results: list) -> list[dict]:
        summary = []
        for result in rollback_results:
            item = {
                "ok": result.ok,
                "summary": result.summary,
                "warnings": result.warnings,
            }
            if isinstance(result.data, dict):
                item["backup_id"] = result.data.get("backup_id")
                item["restored"] = result.data.get("restored", [])
                item["skipped"] = result.data.get("skipped", [])
            summary.append(item)
        return summary

    def _record_artifacts(
        self,
        context: RuntimeContext,
        task: dict,
        tool_results: list,
    ) -> None:
        if not context.run_dir:
            return
        changed_files = self._changed_files(tool_results)
        if not changed_files:
            return

        path = context.run_dir / "artifacts.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "artifact") if path.exists() else []
        known = {artifact["path"] for artifact in existing}
        next_index = len(existing) + 1
        for artifact_path in sorted(set(changed_files)):
            if artifact_path in known:
                continue
            artifact = {
                "schema_version": "0.1.0",
                "artifact_id": f"artifact-{next_index:04d}",
                "run_id": context.run_id,
                "task_id": task["task_id"],
                "type": self._artifact_type(artifact_path),
                "path": artifact_path,
                "created_by": "CoderAgent",
                "summary": f"Created or modified by {task['task_id']}: {task['title']}",
                "created_at": now_iso(),
            }
            store.append(path, artifact, "artifact")
            known.add(artifact_path)
            next_index += 1

    def _changed_files(self, tool_results: list) -> list[str]:
        changed_files = []
        for result in tool_results:
            if not result.ok or not isinstance(result.data, dict):
                continue
            if result.data.get("path"):
                changed_files.append(result.data["path"])
            changed_files.extend(result.data.get("changed_files", []))
        return changed_files

    def _artifact_type(self, path: str) -> str:
        lowered = path.lower()
        if "test" in lowered or lowered.endswith((".spec.py", ".test.py")):
            return "test_file"
        if lowered.endswith((".md", ".txt", ".rst")):
            return "report"
        return "source_file"

    def _block_task(
        self, task_board: TaskBoard, task_id: str, reason: str, context: RuntimeContext
    ) -> None:
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
        self.store.write(
            agent_dir / "tasks" / "backlog.json",
            {"schema_version": "0.1.0", "tasks": task_board.list_tasks()},
            "task_board",
        )

    def _pending_decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return [
            decision
            for decision in JsonlStore(self.validator).read_all(path, "decision_point")
            if decision["status"] == "pending"
        ]

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted(
            [path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name
        )
        return runs[-1].name if runs else None
