from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from agent_runtime.agents.coder_agent import CoderAgent
from agent_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.candidate_workspace import CandidateWorkspace
from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.core.execution_coordinator import ExecutionCoordinator
from agent_runtime.core.policy_config import load_policy_config
from agent_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.runtime_policy import (
    RuntimeRequestPolicy,
    RuntimeRequestPolicyResult,
    ToolPermissionDenied,
    ToolPermissionPolicy,
)
from agent_runtime.core.task_contract import (
    allows_expected_failure,
)
from agent_runtime.core.task_attempt_runner import TaskAttemptRunner
from agent_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from agent_runtime.core.task_failure import TaskFailureRecorder
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.core.validation_result import ValidationResult
from agent_runtime.core.worker_recorder import WorkerExecutionRecorder
from agent_runtime.core.worker_runner import WorkerRunner
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.defaults import create_default_tool_registry
from agent_runtime.utils.time import now_iso


_VALIDATION_RESULT_LOCK = RLock()


@dataclass(frozen=True)
class TaskExecutionSummary:
    task_id: str
    status: str
    summary: str
    tool_calls: int
    verification_calls: int
    evidence_path: Path | None = None
    validation_refs: list[str] = field(default_factory=list)


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
            if task.evidence_path:
                lines.append(f"  evidence: {task.evidence_path}")
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
        parallel_readonly: bool = False,
        parallel_writes: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.max_tasks = max_tasks
        self.model_client = model_client
        self.parallel_readonly = parallel_readonly
        self.parallel_writes = parallel_writes
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.registry = create_default_tool_registry()
        self.execution_evidence = TaskExecutionEvidenceRecorder(self.validator)
        self.runtime_request_policy = RuntimeRequestPolicy(
            validator=self.validator,
            evidence_recorder=self.execution_evidence,
            record_task_failure=self._record_task_failure,
        )
        self.tool_permission_policy = ToolPermissionPolicy(self.root, self.validator)
        self.task_attempt_runner = TaskAttemptRunner(
            self.execution_evidence,
            actor="ExecuteCommand",
        )
        self.worker_recorder = WorkerExecutionRecorder(self.validator)
        self.worker_runner = WorkerRunner(
            validator=self.validator,
            recorder=self.worker_recorder,
            runtime_profile_builder=RuntimeProfileBuilder(self.validator),
            actor="ExecuteCommand",
        )

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
        policy = load_policy_config(agent_dir, self.validator)
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

        quality_gate = TaskPlanQualityGate(self.root, self.validator).check(run_id, pause_run=True)
        if quality_gate.blocked:
            event_logger.record(
                run_id,
                "run_paused",
                "ExecuteCommand",
                quality_gate.reason,
                {
                    "gate": "task_plan_quality",
                    "task_plan_eval": str(quality_gate.eval_path),
                    "decision_id": (quality_gate.decision or {}).get("decision_id"),
                },
            )
            self.store.write(cost_report_path, budget.cost_report(), "cost_report")
            return ExecuteResult(
                run_id=run_id,
                completed=0,
                blocked=0,
                executed_tasks=[
                    TaskExecutionSummary(
                        task_id="task-plan",
                        status="paused",
                        summary=quality_gate.reason,
                        tool_calls=0,
                        verification_calls=0,
                        evidence_path=quality_gate.eval_path,
                    )
                ],
                cost_report_path=cost_report_path,
            )

        run["status"] = "running"
        run["current_phase"] = "EXECUTE"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ExecuteCommand", "PLAN -> EXECUTE")

        coordinator = ExecutionCoordinator(
            max_tasks=self.max_tasks,
            parallel_readonly=self.parallel_readonly,
            parallel_writes=self.parallel_writes,
            actor="ExecuteCommand",
        )
        selection = coordinator.select_tasks(task_board)
        coordinator.record_selection(context, selection)

        def execute_worker(
            task: dict,
            worker_id: str | None,
            result_id: str | None,
        ) -> TaskExecutionSummary:
            return self._execute_task_with_worker_record(
                task=task,
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=runtime_context,
                worker_id=worker_id,
                result_id=result_id,
            )

        executed = coordinator.execute_selection(
            selection=selection,
            task_board=task_board,
            context=context,
            execute_task=execute_worker,
            allocate_worker_ids=lambda count: self._allocate_worker_ids(context, count),
            allocate_worker_result_ids=lambda count: self._allocate_worker_result_ids(context, count),
        )

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

    def _allocate_worker_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-{index + 1:04d}" for index in range(count)]
        return self.worker_recorder.allocate_worker_ids(context, count)

    def _allocate_worker_result_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-result-{index + 1:04d}" for index in range(count)]
        return self.worker_recorder.allocate_worker_result_ids(context, count)

    def _execute_task_with_worker_record(
        self,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
        worker_id: str | None = None,
        result_id: str | None = None,
    ) -> TaskExecutionSummary:
        run_dir = context.run_dir
        worker_id = worker_id or (
            self._next_jsonl_id(run_dir / "workers.jsonl", "worker") if run_dir else "worker-0001"
        )
        result_id = result_id or (
            self._next_jsonl_id(run_dir / "worker_results.jsonl", "worker-result")
            if run_dir
            else "worker-result-0001"
        )
        return self.worker_runner.run(
            task=task,
            context=context,
            runtime_context=runtime_context,
            execute_task=lambda mounted_context: self._execute_task(
                task=task,
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=mounted_context,
            ),
            artifact_refs=self._task_artifact_refs,
            failure_evidence_refs=self._failure_evidence_refs,
            task_failure_refs=self._task_failure_refs,
            decision_refs=self._task_decision_refs,
            validation_refs=self._task_validation_refs,
            model_call_count=self._jsonl_count,
            worker_id=worker_id,
            result_id=result_id,
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
            action = self._normalize_inline_verification(action, task)
            action = self._replace_unsafe_verification(action, task, context.policy)
            action = self._prepend_python_compile_verification(action, task)
            self._require_non_empty_action(action)
            runtime_request_result = self.runtime_request_policy.handle_runtime_requests(
                action=action,
                task=task,
                task_board=task_board,
                context=context,
            )
            if runtime_request_result is not None:
                return self._runtime_request_task_summary(runtime_request_result)
            decision = self.tool_permission_policy.create_policy_decision_if_needed(
                action=action,
                task=task,
                context=context,
            )
            if decision is not None:
                task_board.update_status(task_id, "blocked")
                task_board.update_notes(task_id, f"Waiting for decision: {decision['decision_id']}")
                self._record_task_failure(
                    context,
                    task,
                    "policy_decision",
                    f"Waiting for decision: {decision['decision_id']}",
                    candidate={"decision_id": decision["decision_id"]},
                )
                if context.event_logger:
                    context.event_logger.record(
                        context.run_id,
                        "task_paused_for_decision",
                        "ExecuteCommand",
                        f"{task_id} paused for {decision['decision_id']}",
                        {"task_id": task_id, "decision_id": decision["decision_id"]},
                    )
                evidence_path = self.execution_evidence.record(
                    context,
                    task,
                    action,
                    [],
                    [],
                    "blocked",
                    f"Waiting for decision: {decision['decision_id']}",
                    actor="ExecuteCommand",
                    candidate={"decision_id": decision["decision_id"]},
                    failure_type="policy_decision",
                )
                return TaskExecutionSummary(
                    task_id=task_id,
                    status="blocked",
                    summary=f"Waiting for decision: {decision['decision_id']}",
                    tool_calls=0,
                    verification_calls=0,
                    evidence_path=evidence_path,
                )
            attempt = self.task_attempt_runner.run(
                task=task,
                task_board=task_board,
                context=context,
                action=action,
                create_candidate_workspace=self._create_candidate_workspace,
                candidate_context=self._candidate_context,
                run_tool_calls=self._run_tool_calls,
                record_validation_results=self._record_validation_results,
                changed_files=self._changed_files,
                promote_candidate_changes=self._promote_candidate_changes,
                record_experiment=self._record_experiment,
                complete_task_after_candidate_promotion=self._complete_task_after_candidate_promotion,
                record_task_failure=self._record_task_failure,
            )
            return TaskExecutionSummary(
                task_id=attempt.task_id,
                status=attempt.status,
                summary=attempt.summary,
                tool_calls=attempt.tool_calls,
                verification_calls=attempt.verification_calls,
                evidence_path=attempt.evidence_path,
                validation_refs=attempt.validation_refs,
            )
        except ToolPermissionDenied as exc:
            fallback_action = locals().get("action")
            if not isinstance(fallback_action, dict):
                fallback_action = {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": str(exc),
                    "tool_calls": [],
                    "verification": [],
                    "completion_notes": str(exc),
                }
            action_with_request = dict(fallback_action)
            action_with_request["runtime_requests"] = [
                *list(action_with_request.get("runtime_requests") or []),
                {
                    "request_type": exc.request_type,
                    "risk": exc.risk,
                    "reason": str(exc),
                    "details": exc.details,
                },
            ]
            runtime_request_result = self.runtime_request_policy.handle_runtime_requests(
                action=action_with_request,
                task=task,
                task_board=task_board,
                context=context,
            )
            if runtime_request_result is not None:
                return self._runtime_request_task_summary(runtime_request_result)
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary=str(exc),
                tool_calls=0,
                verification_calls=0,
            )
        except Exception as exc:  # noqa: BLE001 - execution loop must persist failures
            self._block_task(task_board, task_id, str(exc), context)
            self._record_task_failure(context, task, self._failure_type(exc), str(exc))
            evidence_path = self.execution_evidence.record(
                context,
                task,
                None,
                [],
                [],
                "blocked",
                str(exc),
                actor="ExecuteCommand",
                failure_type=self._failure_type(exc),
            )
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary=str(exc),
                tool_calls=0,
                verification_calls=0,
                evidence_path=evidence_path,
            )

    def _require_non_empty_action(self, action: dict) -> None:
        if (
            not action.get("tool_calls")
            and not action.get("verification")
            and not action.get("runtime_requests")
        ):
            raise RuntimeError("ExecutionAction contained no tool calls, verification, or runtime requests.")

    def _runtime_request_task_summary(
        self,
        result: RuntimeRequestPolicyResult,
    ) -> TaskExecutionSummary:
        return TaskExecutionSummary(
            task_id=result.task_id,
            status=result.status,
            summary=result.summary,
            tool_calls=0,
            verification_calls=0,
            evidence_path=result.evidence_path,
        )

    def _normalize_inline_verification(self, action: dict, task: dict) -> dict:
        if action.get("verification") or not task.get("verification_policy", {}).get("required"):
            return action
        tool_calls = list(action.get("tool_calls") or [])
        verification = [
            call
            for call in tool_calls
            if call.get("tool_name") in {"run_command", "run_tests"}
        ]
        if not verification:
            return action
        normalized = dict(action)
        normalized["tool_calls"] = [
            call
            for call in tool_calls
            if call.get("tool_name") not in {"run_command", "run_tests"}
        ]
        normalized["verification"] = verification
        return normalized

    def _replace_unsafe_verification(self, action: dict, task: dict, policy: dict) -> dict:
        verification = list(action.get("verification") or [])
        if not verification:
            return action
        safe_verification = []
        replaced = False
        for call in verification:
            if call.get("tool_name") not in {"run_command", "run_tests"}:
                safe_verification.append(call)
                continue
            command = str(call.get("args", {}).get("command") or "")
            denial = self.tool_permission_policy.shell_denial(policy, command) if command else None
            if not command or denial is None:
                safe_verification.append(call)
                continue
            if not self._can_replace_verification_denial(denial):
                safe_verification.append(call)
                continue
            replaced = True
        if not replaced:
            return action
        normalized = dict(action)
        normalized["verification"] = [
            *safe_verification,
            *self._default_verification_calls(task, action),
        ]
        normalized["verification"] = self._dedupe_tool_calls(normalized["verification"])
        return normalized

    def _can_replace_verification_denial(self, denial: str) -> bool:
        return any(
            denial.endswith(f": {operator}")
            for operator in {"|", ">", ">>", "<", "2>", "2>>"}
        )

    def _default_verification_calls(self, task: dict, action: dict) -> list[dict]:
        calls = []
        artifacts = [
            *[
                str(call.get("args", {}).get("path"))
                for call in action.get("tool_calls", [])
                if call.get("tool_name") == "write_file" and call.get("args", {}).get("path")
            ],
            *[
                str(artifact)
                for artifact in task.get("expected_artifacts", [])
                if isinstance(artifact, str)
            ],
        ]
        for artifact in dict.fromkeys(artifacts):
            if not isinstance(artifact, str) or not artifact.endswith(".py"):
                continue
            calls.append(
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": f"python -m py_compile {artifact}",
                        "expected_returncodes": [0],
                    },
                    "reason": "safe fallback verification for Python artifact",
                }
            )
        return calls or [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python -c \"print('verification placeholder')\"",
                    "expected_returncodes": [0],
                },
                "reason": "safe fallback verification",
            }
        ]

    def _dedupe_tool_calls(self, calls: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for call in calls:
            key = json.dumps(call, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(call)
        return deduped

    def _prepend_python_compile_verification(self, action: dict, task: dict) -> dict:
        if not action.get("verification"):
            return action
        artifacts = [
            str(path)
            for path in [
                *task.get("expected_changed_files", []),
                *task.get("expected_artifacts", []),
            ]
            if str(path).endswith(".py")
        ]
        if not artifacts or "run_command" not in set(task.get("allowed_tools", [])):
            return action
        compile_calls = [
            {
                "tool_name": "run_command",
                "args": {"command": f"python -m py_compile {artifact}"},
                "reason": "fail fast on Python syntax errors before behavior checks",
            }
            for artifact in sorted(set(artifacts))
        ]
        normalized = dict(action)
        normalized["verification"] = self._dedupe_tool_calls(
            [*compile_calls, *list(action.get("verification") or [])]
        )
        return normalized

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
        stop_verification_on_fatal: bool = False,
    ) -> list:
        results = []
        allowed = set(task["allowed_tools"])
        for call in calls:
            tool_name = call["tool_name"]
            if tool_name not in allowed:
                raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
            self.tool_permission_policy.enforce_tool_permission_profile(
                task,
                tool_name,
                call.get("args", {}),
            )
            result = self.registry.call(
                tool_name,
                self.tool_permission_policy.context_with_approval(
                    context,
                    task,
                    tool_name,
                    call["args"],
                ),
                task_id=task["task_id"],
                agent_id="CoderAgent",
                **self._tool_args(call["args"]),
            )
            if self._accepts_diagnostic_failure(task, tool_name, result):
                result.ok = True
                result.error = None
                result.summary = f"Diagnostic failure accepted: {result.summary}"
            results.append(result)
            if stop_on_failure and not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
            if stop_verification_on_fatal and self._fatal_verification_failure(result):
                break
        return results

    def _fatal_verification_failure(self, result: object) -> bool:
        if getattr(result, "ok", False):
            return False
        data = getattr(result, "data", None)
        stderr = str(data.get("stderr", "")) if isinstance(data, dict) else ""
        summary = str(getattr(result, "summary", ""))
        text = f"{summary}\n{stderr}"
        return any(signal in text for signal in ["SyntaxError", "IndentationError"])

    def _tool_args(self, args: dict) -> dict:
        reserved = {"context", "task_id", "agent_id"}
        return {key: value for key, value in args.items() if key not in reserved}

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
        candidate_workspace: CandidateWorkspace | None = None,
        promoted_files: list[str] | None = None,
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
                "workspace": str(candidate_workspace.root) if candidate_workspace else None,
                "candidate_id": (candidate_workspace.candidate_id if candidate_workspace else None),
                "strategy": candidate_workspace.strategy if candidate_workspace else None,
                "workspace_policy": (
                    candidate_workspace.workspace_policy if candidate_workspace else None
                ),
                "backend_reason": candidate_workspace.backend_reason if candidate_workspace else None,
                "branch_name": candidate_workspace.branch_name if candidate_workspace else None,
                "promoted_files": sorted(set(promoted_files or [])),
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

    def _record_validation_results(
        self,
        context: RuntimeContext,
        task: dict,
        calls: list[dict],
        results: list,
    ) -> list[str]:
        if context.run_dir is None or not results:
            return []
        path = context.run_dir / "validation_results.jsonl"
        store = JsonlStore(self.validator)
        refs: list[str] = []
        with _VALIDATION_RESULT_LOCK:
            existing_count = self._jsonl_count(path)
            for offset, result in enumerate(results, start=1):
                call = calls[offset - 1] if offset <= len(calls) else {}
                raw_args = call.get("args")
                args = raw_args if isinstance(raw_args, dict) else {}
                validation = ValidationResult(
                    validation_result_id=f"validation-{existing_count + offset:04d}",
                    run_id=context.run_id,
                    task_id=task["task_id"],
                    tool_name=str(call.get("tool_name") or "unknown"),
                    command=args.get("command") if isinstance(args.get("command"), str) else None,
                    status="passed" if getattr(result, "ok", False) else "failed",
                    summary=str(getattr(result, "summary", "")),
                    error=getattr(result, "error", None),
                    data=getattr(result, "data", {}) if isinstance(getattr(result, "data", {}), dict) else {},
                    created_at=now_iso(),
                )
                store.append(path, validation.to_dict(), "validation_result")
                refs.append(validation.validation_result_id)
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "validation_results_recorded",
                "ExecuteCommand",
                f"Recorded {len(refs)} validation result(s) for {task['task_id']}.",
                {"task_id": task["task_id"], "validation_refs": refs},
            )
        return refs

    def _record_task_failure(
        self,
        context: RuntimeContext,
        task: dict,
        failure_type: str,
        summary: str,
        contract_check: dict | None = None,
        tool_results: list | None = None,
        verification_results: list | None = None,
        candidate: dict | None = None,
    ) -> None:
        if not context.run_dir:
            return
        evidence = TaskFailureRecorder(context.run_dir, self.validator).record(
            run_id=context.run_id,
            task=task,
            phase="execute",
            failure_type=failure_type,
            summary=summary,
            contract_check=contract_check,
            tool_results=tool_results,
            verification_results=verification_results,
            candidate=candidate,
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_failure_recorded",
                "ExecuteCommand",
                summary,
                {
                    "evidence_id": evidence["evidence_id"],
                    "task_id": task["task_id"],
                    "failure_type": failure_type,
                },
            )

    def _failure_type(self, exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return "tool_permission"
        message = str(exc).lower()
        if message.startswith("tool failed:"):
            return "tool_failure"
        if "no tool calls or verification" in message:
            return "empty_action"
        return "exception"

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
            if result.data.get("path") and result.data.get("backup_id"):
                changed_files.append(result.data["path"])
            changed_files.extend(result.data.get("changed_files", []))
        return changed_files

    def _create_candidate_workspace(
        self,
        context: RuntimeContext,
        task: dict,
    ) -> CandidateWorkspace:
        if context.run_dir is None:
            raise RuntimeError("Cannot isolate candidate without a run directory.")
        return CandidateWorkspace.create(context.root, context.run_dir, task["task_id"])

    def _candidate_context(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
    ) -> RuntimeContext:
        return RuntimeContext(
            root=candidate.root,
            run_id=context.run_id,
            policy=context.policy,
            validator=context.validator,
            event_logger=context.event_logger,
            budget=context.budget,
            agent_dir_override=context.agent_dir,
            run_dir_override=context.run_dir,
        )

    def _promote_candidate_changes(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        changed_files: list[str],
    ) -> list[str]:
        return candidate.promote(changed_files)

    def _complete_task_after_candidate_promotion(
        self,
        task_board: TaskBoard,
        task_id: str,
        notes: str,
    ) -> None:
        try:
            task_board.complete_task(task_id, notes)
        except TaskStateError as exc:
            if not str(exc).startswith("Task not found:"):
                raise
            return

    def _artifact_type(self, path: str) -> str:
        lowered = path.lower()
        if "test" in lowered or lowered.endswith((".spec.py", ".test.py")):
            return "test_file"
        if lowered.endswith((".md", ".txt", ".rst")):
            return "report"
        return "source_file"

    def _task_artifact_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "artifacts.jsonl"
        if not path.exists():
            return []
        artifacts = JsonlStore(self.validator).read_all(path, "artifact")
        return [
            artifact["artifact_id"]
            for artifact in artifacts
            if artifact.get("task_id") == task_id and artifact.get("artifact_id")
        ]

    def _failure_evidence_refs(self, summary: TaskExecutionSummary) -> list[str]:
        if summary.status != "blocked" or summary.evidence_path is None:
            return []
        return [str(summary.evidence_path)]

    def _task_failure_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "task_failures.jsonl"
        if not path.exists():
            return []
        failures = JsonlStore(self.validator).read_all(path, "task_failure_evidence")
        return [
            failure["evidence_id"]
            for failure in failures
            if failure.get("task_id") == task_id and failure.get("evidence_id")
        ]

    def _task_decision_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        decisions = JsonlStore(self.validator).read_all(path, "decision_point")
        refs = []
        for decision in decisions:
            metadata = decision.get("metadata") or {}
            if metadata.get("task_id") == task_id and decision.get("decision_id"):
                refs.append(decision["decision_id"])
        return refs

    def _task_validation_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "validation_results.jsonl"
        if not path.exists():
            return []
        validations = JsonlStore(self.validator).read_all(path, "validation_result")
        return [
            validation["validation_result_id"]
            for validation in validations
            if validation.get("task_id") == task_id and validation.get("validation_result_id")
        ]

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _next_jsonl_id(self, path: Path, prefix: str) -> str:
        return f"{prefix}-{self._jsonl_count(path) + 1:04d}"

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
