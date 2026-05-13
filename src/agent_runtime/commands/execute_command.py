from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from agent_runtime.agents.coder_agent import CoderAgent
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from agent_runtime.core.budget import BudgetController
from agent_runtime.core.candidate_workspace import CandidateWorkspace
from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.core.policy_config import load_policy_config
from agent_runtime.core.runtime_request import RuntimeRequest
from agent_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.task_contract import (
    allows_expected_failure,
    check_completion_contract,
    parallel_safety,
    read_scope,
    write_scope,
)
from agent_runtime.core.task_graph import TaskGraphScheduler
from agent_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from agent_runtime.core.task_failure import TaskFailureRecorder
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.core.validation_result import ValidationResult
from agent_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.tools.patch_tools import PatchApplyError, parse_unified_diff
from agent_runtime.security.shell_guard import ShellGuard, ShellPolicyError
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.defaults import create_default_tool_registry
from agent_runtime.utils.time import now_iso


_VALIDATION_RESULT_LOCK = RLock()


class ToolPermissionDenied(PermissionError):
    def __init__(
        self,
        message: str,
        *,
        request_type: str,
        details: dict,
        risk: str = "medium",
    ) -> None:
        super().__init__(message)
        self.request_type = request_type
        self.details = details
        self.risk = risk


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

        executed: list[TaskExecutionSummary] = []
        selection = self._select_tasks(task_board)
        if context.event_logger:
            context.event_logger.record(
                run_id,
                "task_graph_selection",
                "ExecuteCommand",
                f"Selected {len(selection.selected)} task(s) for {selection.reason}.",
                {"reason": selection.reason, "task_ids": [task["task_id"] for task in selection.selected]},
            )
        if selection.reason in {"readonly_batch_selection", "parallel_safe_batch_selection"}:
            executed.extend(
                self._execute_parallel_batch(
                    tasks=selection.selected,
                    task_board=task_board,
                    context=context,
                    coder=coder,
                    goal_spec=goal_spec,
                    project_config=project_config,
                    runtime_context=runtime_context,
                )
            )
        else:
            for task in selection.selected:
                executed.append(
                    self._execute_task_with_worker_record(
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

    def _select_tasks(self, task_board: TaskBoard):
        scheduler = TaskGraphScheduler(task_board.list_tasks())
        if self.parallel_writes:
            selection = scheduler.select_parallel_safe_batch(self.max_tasks)
            if selection.selected:
                return selection
        if self.parallel_readonly:
            selection = scheduler.select_readonly_batch(self.max_tasks)
            if selection.selected:
                return selection
        return scheduler.select_serial(self.max_tasks)

    def _execute_parallel_batch(
        self,
        tasks: list[dict],
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
    ) -> list[TaskExecutionSummary]:
        if not tasks:
            return []
        if len(tasks) == 1:
            result = self._execute_task_with_worker_record(
                task=tasks[0],
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=runtime_context,
            )
            task_board.promote_unblocked()
            return [result]

        worker_ids = self._allocate_worker_ids(context, len(tasks))
        result_ids = self._allocate_worker_result_ids(context, len(tasks))
        results_by_task_id: dict[str, TaskExecutionSummary] = {}
        with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="agent-readonly") as pool:
            futures = {
                pool.submit(
                    self._execute_task_with_worker_record,
                    task,
                    task_board,
                    context,
                    coder,
                    goal_spec,
                    project_config,
                    runtime_context,
                    worker_ids[index],
                    result_ids[index],
                ): task["task_id"]
                for index, task in enumerate(tasks)
            }
            for future in as_completed(futures):
                task_id = futures[future]
                results_by_task_id[task_id] = future.result()
        task_board.promote_unblocked()
        return [results_by_task_id[task["task_id"]] for task in tasks]

    def _allocate_worker_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-{index + 1:04d}" for index in range(count)]
        start = self._jsonl_count(context.run_dir / "workers.jsonl") + 1
        return [f"worker-{index:04d}" for index in range(start, start + count)]

    def _allocate_worker_result_ids(self, context: RuntimeContext, count: int) -> list[str]:
        if context.run_dir is None:
            return [f"worker-result-{index + 1:04d}" for index in range(count)]
        start = self._jsonl_count(context.run_dir / "worker_results.jsonl") + 1
        return [f"worker-result-{index:04d}" for index in range(start, start + count)]

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
        started_at = now_iso()
        run_dir = context.run_dir
        model_calls_before = self._jsonl_count(run_dir / "model_calls.jsonl") if run_dir else 0
        worker_id = worker_id or (
            self._next_jsonl_id(run_dir / "workers.jsonl", "worker") if run_dir else "worker-0001"
        )
        result_id = result_id or (
            self._next_jsonl_id(run_dir / "worker_results.jsonl", "worker-result")
            if run_dir
            else "worker-result-0001"
        )
        try:
            runtime_mount = self._record_runtime_profile_mount(
                context=context,
                task=task,
                worker_id=worker_id,
                runtime_context=runtime_context,
            )
            summary = self._execute_task(
                task=task,
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=runtime_mount.runtime_context,
            )
        except Exception as exc:
            ended_at = now_iso()
            self._record_worker_execution(
                context=context,
                worker_id=worker_id,
                result_id=result_id,
                task=task,
                status="failed",
                started_at=started_at,
                ended_at=ended_at,
                model_calls=(
                    self._jsonl_count(run_dir / "model_calls.jsonl") - model_calls_before
                    if run_dir
                    else 0
                ),
                tool_calls=0,
                artifact_refs=[],
                validation_refs=[],
                failure_evidence_refs=[],
                summary=str(exc),
                runtime_profile_id=(
                    runtime_mount.runtime_profile_id
                    if "runtime_mount" in locals()
                    else self._default_runtime_profile_id(task)
                ),
            )
            raise
        ended_at = now_iso()
        self._record_worker_execution(
            context=context,
            worker_id=worker_id,
            result_id=result_id,
            task=task,
            status=self._worker_status(summary.status),
            started_at=started_at,
            ended_at=ended_at,
            model_calls=(
                self._jsonl_count(run_dir / "model_calls.jsonl") - model_calls_before
                if run_dir
                else 0
            ),
            tool_calls=summary.tool_calls + summary.verification_calls,
            artifact_refs=self._task_artifact_refs(context, task["task_id"]),
            validation_refs=summary.validation_refs,
            failure_evidence_refs=self._failure_evidence_refs(summary),
            summary=summary.summary,
            runtime_profile_id=runtime_mount.runtime_profile_id,
        )
        return summary

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
            runtime_request_summary = self._handle_runtime_requests(action, task, task_board, context)
            if runtime_request_summary is not None:
                return runtime_request_summary
            decision = self._create_policy_decision_if_needed(action, task, context)
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
            candidate = self._create_candidate_workspace(context, task)
            candidate_context = self._candidate_context(context, candidate)
            if context.event_logger:
                context.event_logger.record(
                    context.run_id,
                    "candidate_workspace_created",
                    "ExecuteCommand",
                    f"Created candidate workspace for {task_id}",
                    {
                        "task_id": task_id,
                        "candidate_id": candidate.candidate_id,
                        "workspace": str(candidate.root),
                    },
                )
            tool_results = self._run_tool_calls(action["tool_calls"], task, candidate_context)
            task_board.update_status(task_id, "testing")
            verification_results = self._run_tool_calls(
                action["verification"],
                task,
                candidate_context,
                stop_on_failure=False,
                stop_verification_on_fatal=True,
            )
            validation_refs = self._record_validation_results(
                context,
                task,
                action.get("verification") or [],
                verification_results,
            )
            contract_check = check_completion_contract(
                task,
                self._changed_files(tool_results),
                verification_results,
            )
            if contract_check.ok:
                promoted_files = self._promote_candidate_changes(
                    context, candidate, contract_check.changed_files
                )
                evidence_path = self.execution_evidence.record(
                    context,
                    task,
                    action,
                    tool_results,
                    verification_results,
                    "done",
                    "Verification passed.",
                    actor="ExecuteCommand",
                    contract_check=contract_check.to_dict(),
                    candidate_workspace=candidate,
                    promoted_files=promoted_files,
                )
                self._record_experiment(
                    context,
                    task,
                    action,
                    tool_results,
                    verification_results,
                    "keep",
                    "Verification passed.",
                    contract_check=contract_check.to_dict(),
                    candidate_workspace=candidate,
                    promoted_files=promoted_files,
                )
                self._complete_task_after_candidate_promotion(
                    task_board,
                    task_id,
                    action.get("completion_notes") or action["summary"],
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
                    evidence_path=evidence_path,
                    validation_refs=validation_refs,
                )
            reason = contract_check.summary()
            evidence_path = self.execution_evidence.record(
                context,
                task,
                action,
                tool_results,
                verification_results,
                "blocked",
                reason,
                actor="ExecuteCommand",
                contract_check=contract_check.to_dict(),
                candidate_workspace=candidate,
                failure_type="contract_violation",
            )
            self._record_experiment(
                context,
                task,
                action,
                tool_results,
                verification_results,
                "discard",
                reason,
                contract_check=contract_check.to_dict(),
                candidate_workspace=candidate,
            )
            task_board.update_status(task_id, "blocked")
            task_board.update_notes(
                task_id,
                f"{reason}; candidate kept isolated at {candidate.root}.",
            )
            self._record_task_failure(
                context,
                task,
                "contract_violation",
                reason,
                contract_check=contract_check.to_dict(),
                tool_results=tool_results,
                verification_results=verification_results,
                candidate={
                    "summary": action["summary"],
                    "changed_files": contract_check.changed_files,
                },
            )
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
                evidence_path=evidence_path,
                validation_refs=validation_refs,
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
            return self._handle_runtime_requests(action_with_request, task, task_board, context) or TaskExecutionSummary(
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

    def _handle_runtime_requests(
        self,
        action: dict,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
    ) -> TaskExecutionSummary | None:
        requests = action.get("runtime_requests") or []
        if not requests:
            return None
        recorded = [
            self._record_runtime_request(context, task, request)
            for request in requests
            if isinstance(request, dict)
        ]
        if not recorded:
            return None
        needs_decision = [request for request in recorded if request["risk"] in {"medium", "high"}]
        decision = self._create_runtime_request_decision(context, task, needs_decision) if needs_decision else None
        final_requests = []
        for request in recorded:
            if decision and request["runtime_request_id"] in decision["metadata"].get("runtime_request_ids", []):
                request = dict(request)
                request["status"] = "decision_created"
                request["decision_id"] = decision["decision_id"]
                self._rewrite_runtime_request(context, request)
            final_requests.append(request)

        reason = self._runtime_request_block_reason(final_requests, decision)
        task_board.update_status(task["task_id"], "blocked")
        task_board.update_notes(task["task_id"], reason)
        self._record_task_failure(
            context,
            task,
            "runtime_request",
            reason,
            candidate={
                "runtime_request_ids": [request["runtime_request_id"] for request in final_requests],
                "decision_id": decision["decision_id"] if decision else None,
            },
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_request_blocked_task",
                "ExecuteCommand",
                reason,
                {
                    "task_id": task["task_id"],
                    "runtime_request_ids": [
                        request["runtime_request_id"] for request in final_requests
                    ],
                    "decision_id": decision["decision_id"] if decision else None,
                },
            )
        evidence_path = self.execution_evidence.record(
            context,
            task,
            action,
            [],
            [],
            "blocked",
            reason,
            actor="ExecuteCommand",
            candidate={
                "runtime_request_ids": [request["runtime_request_id"] for request in final_requests],
                "decision_id": decision["decision_id"] if decision else None,
            },
            failure_type="runtime_request",
        )
        return TaskExecutionSummary(
            task_id=task["task_id"],
            status="blocked",
            summary=reason,
            tool_calls=0,
            verification_calls=0,
            evidence_path=evidence_path,
        )

    def _record_runtime_request(
        self,
        context: RuntimeContext,
        task: dict,
        request: dict,
    ) -> dict:
        raw_details = request.get("details")
        details: dict = raw_details if isinstance(raw_details, dict) else {}
        runtime_request = RuntimeRequest(
            runtime_request_id=(
                self._next_jsonl_id(context.run_dir / "runtime_requests.jsonl", "runtime-request")
                if context.run_dir
                else "runtime-request-0001"
            ),
            run_id=context.run_id,
            task_id=task["task_id"],
            request_type=str(request["request_type"]),
            risk=str(request["risk"]),
            reason=str(request["reason"]),
            details=details,
            status="recorded",
            created_at=now_iso(),
        ).to_dict()
        self.validator.validate("runtime_request", runtime_request)
        if context.run_dir:
            JsonlStore(self.validator).append(
                context.run_dir / "runtime_requests.jsonl",
                runtime_request,
                "runtime_request",
            )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_request_recorded",
                "ExecuteCommand",
                f"{runtime_request['request_type']}: {runtime_request['reason']}",
                {
                    "task_id": task["task_id"],
                    "runtime_request_id": runtime_request["runtime_request_id"],
                    "request_type": runtime_request["request_type"],
                    "risk": runtime_request["risk"],
                },
            )
        return runtime_request

    def _rewrite_runtime_request(self, context: RuntimeContext, updated: dict) -> None:
        if context.run_dir is None:
            return
        path = context.run_dir / "runtime_requests.jsonl"
        store = JsonlStore(self.validator)
        requests = store.read_all(path, "runtime_request") if path.exists() else []
        rewritten = [
            updated if item["runtime_request_id"] == updated["runtime_request_id"] else item
            for item in requests
        ]
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rewritten),
            encoding="utf-8",
        )

    def _create_runtime_request_decision(
        self,
        context: RuntimeContext,
        task: dict,
        requests: list[dict],
    ) -> dict | None:
        if context.run_dir is None:
            return None
        decisions_path = context.run_dir / "decisions.jsonl"
        decision_id = self._next_jsonl_id(decisions_path, "decision")
        request_ids = [request["runtime_request_id"] for request in requests]
        decision = {
            "schema_version": "0.1.0",
            "decision_id": decision_id,
            "status": "pending",
            "question": self._runtime_request_question(task, requests),
            "recommended_option_id": "review_contract",
            "options": [
                {
                    "option_id": "review_contract",
                    "label": "Review contract",
                    "tradeoff": "Pause execution and revise scope, context, tools, budget, or model routing deliberately.",
                    "action": "require_replan",
                },
                {
                    "option_id": "reject_request",
                    "label": "Reject request",
                    "tradeoff": "Keep current task boundary and require the worker to find another valid path.",
                    "action": "record_constraint",
                },
            ],
            "default_option_id": "review_contract",
            "impact": self._runtime_request_impact(requests),
            "selected_option_id": None,
            "created_at": now_iso(),
            "metadata": {
                "kind": "runtime_request",
                "task_id": task["task_id"],
                "runtime_request_ids": request_ids,
                "request_types": sorted({request["request_type"] for request in requests}),
            },
            "resolved_at": None,
        }
        self.validator.validate("decision_point", decision)
        JsonlStore(self.validator).append(decisions_path, decision, "decision_point")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "decision_created",
                "ExecuteCommand",
                str(decision["question"]),
                {"decision_id": decision_id, "runtime_request_ids": request_ids},
            )
        return decision

    def _runtime_request_question(self, task: dict, requests: list[dict]) -> str:
        kinds = ", ".join(sorted({request["request_type"] for request in requests}))
        return f"Runtime request for {task['task_id']} requires contract review: {kinds}."

    def _runtime_request_impact(self, requests: list[dict]) -> dict:
        risk = "high" if any(request["risk"] == "high" for request in requests) else "medium"
        return {"scope": "medium", "budget": "medium", "risk": risk, "quality": "medium"}

    def _runtime_request_block_reason(self, requests: list[dict], decision: dict | None) -> str:
        ids = ", ".join(request["runtime_request_id"] for request in requests)
        if decision:
            return f"Runtime request requires decision {decision['decision_id']}: {ids}"
        return f"Runtime request recorded for contract review: {ids}"

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
            denial = self._shell_denial(policy, command) if command else None
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
            self._enforce_tool_permission_profile(task, tool_name, call.get("args", {}))
            result = self.registry.call(
                tool_name,
                self._context_with_approval(context, task, tool_name, call["args"]),
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

    def _enforce_tool_permission_profile(self, task: dict, tool_name: str, args: dict) -> None:
        write_tools = {"write_file", "apply_patch", "restore_backup"}
        if tool_name not in write_tools:
            self._enforce_read_scope(task, tool_name, args)
            return
        if parallel_safety(task) == "readonly" or not write_scope(task):
            raise PermissionError(
                f"ToolPermissionProfile denied write tool for readonly task {task['task_id']}: "
                f"{tool_name}"
            )
        if not isinstance(task.get("write_scope"), list):
            return
        for path in self._write_paths_for_tool(tool_name, args):
            if not self._path_in_scope(path, write_scope(task)):
                raise ToolPermissionDenied(
                    f"ToolPermissionProfile denied write path for {task['task_id']}: {path}",
                    request_type="scope_expansion",
                    details={"write_scope": [path]},
                )

    def _enforce_read_scope(self, task: dict, tool_name: str, args: dict) -> None:
        path = None
        if tool_name in {"read_file", "list_files", "search_text", "find_files", "diff_workspace"}:
            path = str(args.get("path") or ".")
        if path is None:
            return
        if not isinstance(task.get("read_scope"), list):
            return
        scope = read_scope(task)
        if scope and not self._path_in_scope(path, scope):
            raise ToolPermissionDenied(
                f"ToolPermissionProfile denied read path for {task['task_id']}: {path}",
                request_type="context_request",
                details={"read_scope": [path], "context_requirements": {"requested_paths": [path]}},
            )

    def _write_paths_for_tool(self, tool_name: str, args: dict) -> list[str]:
        if tool_name == "write_file" and args.get("path"):
            return [str(args["path"])]
        if tool_name == "apply_patch":
            patch_text = args.get("patch") if args.get("patch") is not None else args.get("diff")
            if not isinstance(patch_text, str):
                return []
            try:
                return [file_patch.path for file_patch in parse_unified_diff(patch_text)]
            except PatchApplyError:
                return []
        return []

    def _path_in_scope(self, path: str, scope: list[str]) -> bool:
        normalized = self._normalize_scope_path(path)
        for item in scope:
            allowed = self._normalize_scope_path(str(item))
            if allowed in {"", "."}:
                return True
            if allowed.endswith("/"):
                if normalized.startswith(allowed):
                    return True
            elif normalized == allowed:
                return True
        return False

    def _normalize_scope_path(self, path: str) -> str:
        normalized = path.replace("\\", "/").strip()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized and not normalized.endswith("/") and "." not in normalized.rsplit("/", 1)[-1]:
            normalized += "/"
        return normalized

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
            agent_dir_override=context.agent_dir,
            run_dir_override=context.run_dir,
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

    def _record_worker_execution(
        self,
        context: RuntimeContext,
        worker_id: str,
        result_id: str,
        task: dict,
        status: str,
        started_at: str,
        ended_at: str,
        model_calls: int,
        tool_calls: int,
        artifact_refs: list[str],
        validation_refs: list[str],
        failure_evidence_refs: list[str],
        summary: str,
        runtime_profile_id: str,
    ) -> None:
        if context.run_dir is None:
            return
        store = JsonlStore(self.validator)
        invocation = WorkerInvocation(
            worker_invocation_id=worker_id,
            run_id=context.run_id or "",
            task_id=task["task_id"],
            agent_id=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            runtime_profile_id=runtime_profile_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            summary=f"Execute {task['task_id']} through {runtime_profile_id}.",
        )
        result = WorkerResult(
            worker_result_id=result_id,
            worker_invocation_id=worker_id,
            run_id=context.run_id or "",
            task_id=task["task_id"],
            status=self._worker_result_status(status),
            artifact_refs=artifact_refs,
            validation_refs=validation_refs,
            failure_evidence_refs=failure_evidence_refs,
            cost=WorkerCost(model_calls=max(model_calls, 0), tool_calls=tool_calls),
            summary=summary,
        )
        store.append(context.run_dir / "workers.jsonl", invocation.to_dict(), "worker_invocation")
        store.append(context.run_dir / "worker_results.jsonl", result.to_dict(), "worker_result")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "worker_recorded",
                "ExecuteCommand",
                f"{worker_id} -> {result.status}",
                {
                    "worker_invocation_id": worker_id,
                    "worker_result_id": result_id,
                    "task_id": task["task_id"],
                    "runtime_profile_id": runtime_profile_id,
                },
            )

    def _worker_status(self, task_status: str) -> str:
        if task_status == "done":
            return "succeeded"
        if task_status == "blocked":
            return "failed"
        return "cancelled"

    def _worker_result_status(self, worker_status: str) -> str:
        return {
            "succeeded": "succeeded",
            "failed": "failed",
            "denied": "denied",
            "timeout": "timeout",
        }.get(worker_status, "partial")

    def _default_runtime_profile_id(self, task: dict) -> str:
        role = str(task.get("role") or "CoderAgent").lower().replace("agent", "")
        return f"runtime-profile-execute-{role or 'coder'}"

    def _record_runtime_profile_mount(
        self,
        context: RuntimeContext,
        task: dict,
        worker_id: str,
        runtime_context: dict,
    ):
        return RuntimeProfileBuilder(self.validator).build_and_record(
            context=context,
            task=task,
            worker_id=worker_id,
            runtime_context=runtime_context,
            artifact_refs=self._task_artifact_refs(context, task["task_id"]),
            failure_evidence_refs=self._task_failure_refs(context, task["task_id"]),
            decision_refs=self._task_decision_refs(context, task["task_id"]),
            validation_refs=self._task_validation_refs(context, task["task_id"]),
        )

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
