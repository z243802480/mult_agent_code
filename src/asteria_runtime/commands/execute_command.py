from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.core.agent_harness import load_harness_observations
from asteria_runtime.core.execution_action_preparer import ExecutionActionPreparer
from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.plugin_manifest import PluginManifestLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.run_state_finalizer import RunStateFinalizer
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.core.runtime_policy import (
    RuntimeRequestPolicy,
    RuntimeRequestPolicyResult,
    ToolPermissionDenied,
    ToolPermissionPolicy,
)
from asteria_runtime.core.task_blocking_handler import BlockingResult, TaskBlockingHandler
from asteria_runtime.core.task_attempt_runner import TaskAttemptRunner
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder, WorkerExecutionSlot
from asteria_runtime.core.worker_runner import WorkerRunner
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.defaults import create_default_tool_registry


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
        self.hook_manager = RuntimeHookManager(self.validator)
        self.action_preparer = ExecutionActionPreparer(self.tool_permission_policy.shell_denial)
        self.task_attempt_runner = TaskAttemptRunner(
            self.execution_evidence,
            actor="ExecuteCommand",
        )
        self.worker_recorder = WorkerExecutionRecorder(self.validator)
        self.evidence_sink = ExecutionEvidenceSink(self.validator, actor="ExecuteCommand")
        self.candidate_gateway = CandidateExecutionGateway()
        self.blocking_handler = TaskBlockingHandler(
            self.execution_evidence,
            self.evidence_sink,
            actor="ExecuteCommand",
        )
        self.tool_gateway = ToolExecutionGateway(
            self.registry,
            self.tool_permission_policy,
            hook_manager=self.hook_manager,
            actor="ExecuteCommand",
        )
        self.run_state_finalizer = RunStateFinalizer(
            self.store,
            self.validator,
            actor="ExecuteCommand",
        )
        self.worker_runner = WorkerRunner(
            validator=self.validator,
            recorder=self.worker_recorder,
            runtime_profile_builder=RuntimeProfileBuilder(self.validator),
            hook_manager=self.hook_manager,
            actor="ExecuteCommand",
        )

    def run(self) -> ExecuteResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `asteria plan` first.")
        run_dir = run_store.run_dir(run_id)
        run = run_store.load_run(run_id)
        policy = load_policy_config(agent_dir, self.validator)
        self.hook_manager.configure(policy)
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
        self._record_plugin_manifests(agent_dir, policy, context)
        model_client = self._model_client(run_dir, budget)
        coder = CoderAgent(model_client, self.validator)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)
        runtime_context = ContextLoader(self.root, self.validator).load(run_id)

        quality_gate = TaskPlanQualityGate(self.root, self.validator).check(
            run_id,
            pause_run=True,
            blocking=self._task_plan_quality_gate_blocks(policy),
        )
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
            worker_slot: WorkerExecutionSlot,
        ) -> TaskExecutionSummary:
            return self._execute_task_with_worker_record(
                task=task,
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=runtime_context,
                worker_slot=worker_slot,
            )

        executed = coordinator.execute_selection(
            selection=selection,
            task_board=task_board,
            context=context,
            execute_task=execute_worker,
            allocate_worker_slots=self.worker_recorder.allocate_execution_slots,
        )
        AgentRunGraphBuilder(self.validator).write(run_dir, run_id=run_id)

        final_state = self.run_state_finalizer.finalize(
            agent_dir=agent_dir,
            run_dir=run_dir,
            run_store=run_store,
            run=run,
            task_board=task_board,
            budget=budget,
            executed=executed,
            cost_report_path=cost_report_path,
            event_logger=event_logger,
        )

        return ExecuteResult(
            run_id=run_id,
            completed=final_state.completed,
            blocked=final_state.blocked,
            executed_tasks=executed,
            cost_report_path=cost_report_path,
        )

    def _task_plan_quality_gate_blocks(self, policy: dict) -> bool:
        agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
        return bool(agent_loop.get("task_plan_quality_gate_blocks", False))

    def _execute_task_with_worker_record(
        self,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
        worker_slot: WorkerExecutionSlot,
    ) -> TaskExecutionSummary:
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
            artifact_refs=self.evidence_sink.artifact_refs,
            failure_evidence_refs=self._failure_evidence_refs,
            task_failure_refs=self.evidence_sink.task_failure_refs,
            decision_refs=self.evidence_sink.decision_refs,
            validation_refs=self.evidence_sink.validation_refs,
            model_call_count=self._jsonl_count,
            worker_id=worker_slot.worker_id,
            result_id=worker_slot.result_id,
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
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="start",
                phase="execute",
                status="running",
                title="Worker action requested",
                summary=f"Asked the coder model to propose execution steps for {task_id}.",
                data={
                    "task_id": task_id,
                    "available_tools": self.registry.names(),
                },
            )
            self._refresh_harness_observations(runtime_context, context)
            action = coder.propose_action(
                task=task,
                goal_spec=goal_spec,
                project_config=project_config,
                available_tools=self.registry.names(),
                run_id=context.run_id or "",
                runtime_context=runtime_context,
            )
            action = self.action_preparer.prepare(action, task, context.policy)
            tool_calls = list(action.get("tool_calls") or [])
            verification = list(action.get("verification") or [])
            runtime_requests = list(action.get("runtime_requests") or [])
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title="Worker action proposed",
                summary=(
                    f"Prepared {len(tool_calls)} tool call(s), "
                    f"{len(verification)} verification step(s), "
                    f"and {len(runtime_requests)} runtime request(s)."
                ),
                data={
                    "task_id": task_id,
                    "tool_call_count": len(tool_calls),
                    "verification_count": len(verification),
                    "runtime_request_count": len(runtime_requests),
                    "summary": action.get("summary", ""),
                },
            )
            runtime_request_result = self.runtime_request_policy.handle_runtime_requests(
                action=action,
                task=task,
                task_board=task_board,
                context=context,
            )
            if runtime_request_result is not None:
                self._record_runtime_request_progress(context, task, runtime_request_result)
                return self._runtime_request_task_summary(runtime_request_result)
            decision = self.tool_permission_policy.create_policy_decision_if_needed(
                action=action,
                task=task,
                context=context,
            )
            if decision is not None:
                blocked = self.blocking_handler.block_for_policy_decision(
                    context=context,
                    task_board=task_board,
                    task=task,
                    action=action,
                    decision=decision,
                )
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="decision",
                    phase="blocked",
                    status="waiting_user",
                    title="Tool permission decision required",
                    summary=blocked.summary,
                    evidence_refs=self._refs(blocked.evidence_path),
                    data={
                        "task_id": task_id,
                        "decision_id": decision.get("decision_id"),
                        "risk": decision.get("risk"),
                        "reason": decision.get("reason"),
                    },
                )
                return self._blocked_task_summary(blocked)
            attempt = self.task_attempt_runner.run(
                task=task,
                task_board=task_board,
                context=context,
                runtime_context=runtime_context,
                action=action,
                create_candidate_workspace=self.candidate_gateway.create_workspace,
                candidate_context=self.candidate_gateway.candidate_context,
                run_tool_calls=self.tool_gateway.run_tool_calls,
                record_validation_results=self.evidence_sink.record_validation_results,
                changed_files=self.evidence_sink.changed_files,
                promote_candidate_changes=self.candidate_gateway.promote_changes,
                record_experiment=self.evidence_sink.record_experiment,
                complete_task_after_candidate_promotion=self.candidate_gateway.complete_after_promotion,
                record_task_failure=self.evidence_sink.record_task_failure,
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
                self._record_runtime_request_progress(context, task, runtime_request_result)
                return self._runtime_request_task_summary(runtime_request_result)
            blocked = self.blocking_handler.block_for_failure(
                context=context,
                task_board=task_board,
                task=task,
                reason=str(exc),
                failure_type="tool_permission_denied",
                action=fallback_action if isinstance(fallback_action, dict) else None,
            )
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="blocked",
                status="blocked",
                title="Task action blocked before tools",
                summary=str(exc),
                evidence_refs=self._refs(blocked.evidence_path),
                data={
                    "task_id": task_id,
                    "failure_type": "tool_permission_denied",
                    "error_type": type(exc).__name__,
                },
            )
            return self._blocked_task_summary(blocked)
        except Exception as exc:  # noqa: BLE001 - execution loop must persist failures
            failure_type = self._failure_type(exc)
            blocked = self.blocking_handler.block_for_failure(
                context=context,
                task_board=task_board,
                task=task,
                reason=str(exc),
                failure_type=failure_type,
            )
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="blocked",
                status="blocked",
                title="Task action failed before tools",
                summary=str(exc),
                evidence_refs=self._refs(blocked.evidence_path),
                data={
                    "task_id": task_id,
                    "failure_type": failure_type,
                    "error_type": type(exc).__name__,
                },
            )
            return self._blocked_task_summary(blocked)

    def _refresh_harness_observations(
        self,
        runtime_context: dict,
        context: RuntimeContext,
    ) -> None:
        observations = load_harness_observations(context.run_dir)
        if observations:
            runtime_context["harness_observations"] = observations

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

    def _blocked_task_summary(self, result: BlockingResult) -> TaskExecutionSummary:
        return TaskExecutionSummary(
            task_id=result.task_id,
            status=result.status,
            summary=result.summary,
            tool_calls=0,
            verification_calls=0,
            evidence_path=result.evidence_path,
        )

    def _record_runtime_request_progress(
        self,
        context: RuntimeContext,
        task: dict,
        result: RuntimeRequestPolicyResult,
    ) -> None:
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="decision",
            phase="blocked",
            status="waiting_user",
            title="Runtime request created",
            summary=result.summary,
            evidence_refs=self._refs(result.evidence_path),
            data={
                "task_id": result.task_id,
                "status": result.status,
            },
        )

    def _record_progress(
        self,
        context: RuntimeContext,
        task: dict,
        *,
        channel: str,
        event_type: str,
        phase: str,
        status: str,
        title: str,
        summary: str,
        evidence_refs: list[str] | None = None,
        data: dict | None = None,
    ) -> None:
        if context.run_id is None:
            return
        run_dir = context.root / ".asteria" / "runs" / context.run_id
        logger = UserProgressLogger(run_dir / "user_progress.jsonl", context.validator)
        logger.record(
            run_id=context.run_id,
            channel=channel,
            event_type=event_type,
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            evidence_refs=evidence_refs or [],
            data={
                "task_id": task.get("task_id"),
                "task_title": task.get("title"),
                **(data or {}),
            },
        )

    def _refs(self, path: Path | None) -> list[str]:
        if path is None:
            return []
        return [str(path)]

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
        self.evidence_sink.record_task_failure(
            context=context,
            task=task,
            failure_type=failure_type,
            summary=summary,
            contract_check=contract_check,
            tool_results=tool_results,
            verification_results=verification_results,
            candidate=candidate,
        )

    def _record_plugin_manifests(
        self,
        agent_dir: Path,
        policy: dict,
        context: RuntimeContext,
    ) -> None:
        manifests = PluginManifestLoader(self.validator).load(agent_dir, policy)
        if not manifests or context.event_logger is None:
            return
        context.event_logger.record(
            context.run_id,
            "plugin_manifests_loaded",
            "ExecuteCommand",
            f"Loaded {len(manifests)} plugin manifest(s).",
            {
                "plugins": [
                    {
                        "plugin_id": item.plugin_id,
                        "status": item.status,
                        "reason": item.reason,
                        "hook_subscriptions": item.manifest.get("hook_subscriptions", []),
                    }
                    for item in manifests
                ]
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

    def _failure_evidence_refs(self, summary: TaskExecutionSummary) -> list[str]:
        if summary.status != "blocked" or summary.evidence_path is None:
            return []
        return [str(summary.evidence_path)]

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

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
