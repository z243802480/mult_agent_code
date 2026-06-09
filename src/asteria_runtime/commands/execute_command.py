from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.core.agent_harness import load_harness_observations, load_raw_tool_observations
from asteria_runtime.core.agent_loop_decision import (
    persist_agent_loop_decision,
    recommended_command_for_next_action,
)
from asteria_runtime.core.agent_loop_executor import (
    complete_subagent_worker_execution,
    persist_agent_loop_execution_result,
    persist_subagent_child_plan_for_execution,
    subagent_worker_observation_payload,
)
from asteria_runtime.core.agent_loop_observation import (
    persist_agent_loop_observation_for_execution,
)
from asteria_runtime.core.agent_loop_run_summary import (
    build_agent_loop_run_summary,
    persist_agent_loop_run_summary,
)
from asteria_runtime.core.agent_tool_surface import (
    model_tool_surface_for_task,
    model_tools_available_for_task,
)
from asteria_runtime.core.execution_action_preparer import ExecutionActionPreparer
from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.plugin_manifest import PluginManifestLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.core.run_state_finalizer import RunStateFinalizer
from asteria_runtime.core.run_config import effective_policy_for_run
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
from asteria_runtime.models.model_failure import classify_model_failure
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.defaults import create_default_tool_registry
from asteria_runtime.utils.time import now_iso


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
        task_ids: set[str] | None = None,
        context_overrides: dict | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.max_tasks = max_tasks
        self.model_client = model_client
        self.parallel_readonly = parallel_readonly
        self.parallel_writes = parallel_writes
        self.task_ids = frozenset(task_ids or set())
        self.context_overrides = dict(context_overrides or {})
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
        policy = effective_policy_for_run(
            policy=load_policy_config(agent_dir, self.validator),
            run_dir=run_dir,
            validator=self.validator,
        )
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
        runtime_context.update(self.context_overrides)
        prompt_envelope = persist_prompt_envelope(
            root=self.root,
            run_dir=run_dir,
            run_id=run_id,
            mode="execute",
            policy=policy,
            validator=self.validator,
            tool_names=self.registry.names(),
            event_logger=event_logger,
            progress_logger=UserProgressLogger(run_dir / "user_progress.jsonl", self.validator),
            phase="execute",
            actor="ExecuteCommand",
        )
        runtime_context["prompt_envelope"] = prompt_envelope.context_ref()

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
            task_ids=self.task_ids,
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
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("task_plan_quality_gate_blocks", False))

    def _agent_loop_max_rounds(self, policy: dict) -> int:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        try:
            value = int(agent_loop.get("max_rounds_per_task") or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(value, 8))

    def _subagent_child_max_rounds(self, policy: dict) -> int:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        try:
            value = int(agent_loop.get("subagent_max_rounds_per_task") or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(value, 4))

    def _execute_subagent_child_loop(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
        available_tools: list[str],
        parent_decision: dict | None,
        parent_execution: dict | None,
    ) -> tuple[TaskExecutionSummary, dict | None]:
        task_id = str(task["task_id"])
        if not isinstance(parent_decision, dict) or not isinstance(parent_execution, dict):
            self._mark_task_blocked(task_board, task_id)
            return (
                TaskExecutionSummary(
                    task_id=task_id,
                    status="blocked",
                    summary="Subagent action could not start because parent decision/execution evidence is missing.",
                    tool_calls=0,
                    verification_calls=0,
                ),
                None,
            )
        worker_id = str(parent_execution.get("worker_invocation_id") or "")
        if not worker_id:
            self._mark_task_blocked(task_board, task_id)
            return (
                TaskExecutionSummary(
                    task_id=task_id,
                    status="blocked",
                    summary="Subagent action could not start because worker slot evidence is missing.",
                    tool_calls=0,
                    verification_calls=0,
                ),
                None,
            )
        child_task = self._subagent_child_task(task, parent_decision, parent_execution)
        child_runtime_context = self._subagent_child_runtime_context(
            runtime_context,
            parent_decision=parent_decision,
            parent_execution=parent_execution,
        )
        runtime_mount = self.worker_runner.runtime_profile_builder.build_and_record(
            context=context,
            task=child_task,
            worker_id=worker_id,
            runtime_context=child_runtime_context,
            artifact_refs=self.evidence_sink.artifact_refs(context, task_id),
            failure_evidence_refs=self.evidence_sink.task_failure_refs(context, task_id),
            decision_refs=self.evidence_sink.decision_refs(context, task_id),
            validation_refs=self.evidence_sink.validation_refs(context, task_id),
        )
        child_runtime_context = runtime_mount.runtime_context
        child_runtime_context["subagent_worker"]["runtime_profile_id"] = (
            runtime_mount.runtime_profile_id
        )
        child_plan = persist_subagent_child_plan_for_execution(
            run_dir=context.run_dir,
            validator=context.validator,
            decision=parent_decision,
            execution_result=parent_execution,
            task=child_task,
            policy=context.policy,
        )
        child_plan_refs = (
            [str(child_plan["subagent_child_plan_id"])] if isinstance(child_plan, dict) else []
        )
        if isinstance(child_plan, dict):
            child_runtime_context["subagent_child_plan"] = child_plan
            child_runtime_context["subagent_worker"]["child_plan_refs"] = child_plan_refs
            if self._is_readonly_fanout_child_plan(child_plan):
                return self._execute_subagent_readonly_fanout(
                    task=task,
                    task_board=task_board,
                    context=context,
                    coder=coder,
                    goal_spec=goal_spec,
                    project_config=project_config,
                    runtime_context=child_runtime_context,
                    parent_decision=parent_decision,
                    parent_execution=parent_execution,
                    child_plan=child_plan,
                    child_plan_refs=child_plan_refs,
                )
        child_max_rounds = self._subagent_child_max_rounds(context.policy)
        child_runtime_context["current_worker_invocation_id"] = worker_id
        child_runtime_context["current_worker_result_id"] = str(
            parent_execution.get("worker_result_id") or ""
        )
        self._record_progress(
            context,
            task,
            channel="execution_chain",
            event_type="message",
            phase="execute",
            status="running",
            title="Subagent worker started",
            summary=f"Started child worker {worker_id} for {task_id}.",
            transcript_kind="subagent_summary",
            ui_intent="work_progress",
            data={
                "task_id": task_id,
                "worker_invocation_id": worker_id,
                "runtime_profile_id": runtime_mount.runtime_profile_id,
                "parallel_safety": child_task.get("parallel_safety"),
                "subagent_child_plan": child_plan or {},
                "parent_agent_loop_execution": parent_execution,
            },
        )
        child_latest_observation: dict | None = None
        child_latest_execution: dict | None = None
        child_latest_summary: TaskExecutionSummary | None = None
        child_model_calls = 0
        child_tool_calls = 0
        child_validation_refs: list[str] = []
        child_failure_refs: list[str] = []
        for child_round in range(1, child_max_rounds + 1):
            child_runtime_context["agent_loop_round"] = {
                "index": child_round,
                "max_rounds": child_max_rounds,
                "latest_observation": child_latest_observation or {},
                "scope": "subagent_child",
            }
            if child_latest_observation:
                child_runtime_context["latest_agent_loop_observation"] = child_latest_observation
            child_action = coder.propose_action(
                task=child_task,
                goal_spec=goal_spec,
                project_config=project_config,
                available_tools=available_tools,
                run_id=context.run_id or "",
                runtime_context=child_runtime_context,
            )
            child_model_calls += 1
            child_action = self.action_preparer.prepare(child_action, child_task, context.policy)
            child_decision = child_action.get("agent_loop_decision")
            child_execution = None
            if isinstance(child_decision, dict):
                self._attach_parent_worker_to_loop_decision(child_decision, child_runtime_context)
                persist_agent_loop_decision(
                    run_dir=context.run_dir,
                    validator=context.validator,
                    decision=child_decision,
                )
                child_execution = persist_agent_loop_execution_result(
                    run_dir=context.run_dir,
                    validator=context.validator,
                    decision=child_decision,
                    create_decision_point=True,
                )
                child_latest_execution = child_execution
            child_next_action = (
                child_decision.get("next_action", {}) if isinstance(child_decision, dict) else {}
            )
            child_next_kind = str(child_next_action.get("action") or "")
            if child_next_kind != "tool":
                previous_done = (
                    child_latest_summary is not None and child_latest_summary.status == "done"
                )
                done_summary = child_latest_summary.summary if child_latest_summary else ""
                done_evidence_path = (
                    child_latest_summary.evidence_path if child_latest_summary else None
                )
                summary = (
                    "Subagent child worker stopped after a successful observation."
                    if previous_done and child_next_kind == "stop"
                    else (
                        "Subagent child worker did not produce a tool action; parent loop must "
                        f"correct with repair/replan/ask/stop. Got `{child_next_kind or 'missing'}`."
                    )
                )
                return self._complete_subagent_child_worker(
                    task=task,
                    task_board=task_board,
                    context=context,
                    parent_execution=parent_execution,
                    child_execution=child_execution or child_latest_execution,
                    status="succeeded" if previous_done else "failed",
                    summary=done_summary if previous_done else summary,
                    artifact_refs=self.evidence_sink.artifact_refs(context, task_id),
                    validation_refs=child_validation_refs,
                    failure_evidence_refs=child_failure_refs,
                    child_plan_refs=child_plan_refs,
                    model_calls=child_model_calls,
                    tool_calls=child_tool_calls,
                    evidence_path=done_evidence_path if previous_done else None,
                )
            self._reset_task_for_subagent_child_attempt(task_board, task_id)
            attempt = self.task_attempt_runner.run(
                task=child_task,
                task_board=task_board,
                context=context,
                runtime_context=child_runtime_context,
                action=child_action,
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
            child_tool_calls += attempt.tool_calls + attempt.verification_calls
            child_validation_refs.extend(attempt.validation_refs)
            if attempt.status != "done":
                child_failure_refs.extend(self._refs(attempt.evidence_path))
            if isinstance(child_execution, dict):
                child_latest_observation = persist_agent_loop_observation_for_execution(
                    run_dir=context.run_dir,
                    validator=context.validator,
                    execution_result=child_execution,
                    status="succeeded" if attempt.status == "done" else "failed",
                    summary=attempt.summary,
                    evidence_refs=self._refs(attempt.evidence_path) + attempt.validation_refs,
                    next_recommended_action="stop" if attempt.status == "done" else "repair",
                )
            child_latest_summary = TaskExecutionSummary(
                task_id=attempt.task_id,
                status=attempt.status,
                summary=attempt.summary,
                tool_calls=attempt.tool_calls,
                verification_calls=attempt.verification_calls,
                evidence_path=attempt.evidence_path,
                validation_refs=attempt.validation_refs,
            )
            if attempt.status == "done":
                return self._complete_subagent_child_worker(
                    task=task,
                    task_board=task_board,
                    context=context,
                    parent_execution=parent_execution,
                    child_execution=child_execution,
                    status="succeeded",
                    summary=attempt.summary,
                    artifact_refs=self.evidence_sink.artifact_refs(context, task_id),
                    validation_refs=child_validation_refs,
                    failure_evidence_refs=child_failure_refs,
                    child_plan_refs=child_plan_refs,
                    model_calls=child_model_calls,
                    tool_calls=child_tool_calls,
                    evidence_path=attempt.evidence_path,
                )
            if not self._should_continue_subagent_child_loop(
                context=context,
                round_index=child_round,
                max_rounds=child_max_rounds,
                observation=child_latest_observation,
            ):
                break
        summary = (
            child_latest_summary.summary
            if child_latest_summary is not None
            else "Subagent child worker exhausted its bounded loop without a usable action."
        )
        return self._complete_subagent_child_worker(
            task=task,
            task_board=task_board,
            context=context,
            parent_execution=parent_execution,
            child_execution=child_latest_execution,
            status="failed",
            summary=summary,
            artifact_refs=self.evidence_sink.artifact_refs(context, task_id),
            validation_refs=child_validation_refs,
            failure_evidence_refs=child_failure_refs,
            child_plan_refs=child_plan_refs,
            model_calls=child_model_calls,
            tool_calls=child_tool_calls,
            evidence_path=child_latest_summary.evidence_path if child_latest_summary else None,
        )

    def _is_readonly_fanout_child_plan(self, child_plan: dict) -> bool:
        if str(child_plan.get("scheduling_strategy") or "") != "parallel_readonly_safe":
            return False
        children = [item for item in child_plan.get("child_tasks") or [] if isinstance(item, dict)]
        if len(children) <= 1:
            return False
        return self._readonly_fanout_gate(child_plan) is None

    def _readonly_fanout_gate(self, child_plan: dict) -> str | None:
        if str(child_plan.get("scheduling_strategy") or "") != "parallel_readonly_safe":
            return "subagent fanout is not using readonly scheduling"
        write_tools = {"write_file", "apply_patch", "restore_backup"}
        for child in child_plan.get("child_tasks") or []:
            if not isinstance(child, dict):
                return "subagent fanout child task is malformed"
            if child.get("write_allowed") is True:
                return "readonly fanout child task allows writes"
            if child.get("write_scope"):
                return "readonly fanout child task has write scope"
            if set(child.get("allowed_tools") or []) & write_tools:
                return "readonly fanout child task exposes write tools"
            if str(child.get("parallel_safety") or "") != "readonly":
                return "readonly fanout child task is not marked readonly"
        return None

    def _execute_subagent_readonly_fanout(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
        parent_decision: dict,
        parent_execution: dict,
        child_plan: dict,
        child_plan_refs: list[str],
    ) -> tuple[TaskExecutionSummary, dict | None]:
        task_id = str(task["task_id"])
        gate_reason = self._readonly_fanout_gate(child_plan)
        if gate_reason is not None:
            return self._complete_subagent_child_worker(
                task=task,
                task_board=task_board,
                context=context,
                parent_execution=parent_execution,
                child_execution=None,
                status="failed",
                summary=f"Readonly fanout blocked by gate: {gate_reason}.",
                artifact_refs=[],
                validation_refs=[],
                failure_evidence_refs=[],
                child_plan_refs=child_plan_refs,
                model_calls=0,
                tool_calls=0,
            )
        children = [item for item in child_plan.get("child_tasks") or [] if isinstance(item, dict)]
        slots = self.worker_recorder.allocate_execution_slots(context, len(children))
        model_calls_before = (
            self._jsonl_count(context.run_dir / "model_calls.jsonl") if context.run_dir else 0
        )
        self._record_progress(
            context,
            task,
            channel="execution_chain",
            event_type="message",
            phase="execute",
            status="running",
            title="Readonly fanout started",
            summary=f"Started {len(children)} readonly child worker(s) for {task_id}.",
            transcript_kind="subagent_summary",
            ui_intent="work_progress",
            data={
                "task_id": task_id,
                "subagent_child_plan_id": child_plan.get("subagent_child_plan_id"),
                "worker_slots": [slot.worker_id for slot in slots],
            },
        )
        summaries_by_id: dict[str, TaskExecutionSummary] = {}
        with ThreadPoolExecutor(
            max_workers=len(children),
            thread_name_prefix="subagent-readonly",
        ) as pool:
            futures = {
                pool.submit(
                    self._execute_one_readonly_fanout_child,
                    child=child,
                    slot=slots[index],
                    task=task,
                    context=context,
                    coder=coder,
                    goal_spec=goal_spec,
                    project_config=project_config,
                    runtime_context=runtime_context,
                    parent_execution=parent_execution,
                    child_plan=child_plan,
                    child_plan_refs=child_plan_refs,
                ): str(child.get("child_task_id") or f"{task_id}-child-{index + 1:02d}")
                for index, child in enumerate(children)
            }
            for future in as_completed(futures):
                child_id = futures[future]
                try:
                    summaries_by_id[child_id] = future.result()
                except Exception as exc:
                    summaries_by_id[child_id] = TaskExecutionSummary(
                        task_id=child_id,
                        status="blocked",
                        summary=str(exc),
                        tool_calls=0,
                        verification_calls=0,
                    )
        summaries = [
            summaries_by_id[str(child.get("child_task_id") or f"{task_id}-child-{index + 1:02d}")]
            for index, child in enumerate(children)
        ]
        validation_refs = [ref for summary in summaries for ref in summary.validation_refs]
        failure_refs = [
            ref
            for summary in summaries
            for ref in self._refs(summary.evidence_path)
            if summary.status != "done"
        ]
        model_calls = (
            self._jsonl_count(context.run_dir / "model_calls.jsonl") - model_calls_before
            if context.run_dir
            else len(summaries)
        )
        tool_calls = sum(summary.tool_calls + summary.verification_calls for summary in summaries)
        succeeded = all(summary.status == "done" for summary in summaries)
        summary_text = (
            f"Readonly fanout completed {len(summaries)} child worker(s)."
            if succeeded
            else "Readonly fanout had failed child worker(s): "
            + "; ".join(summary.summary for summary in summaries if summary.status != "done")
        )
        return self._complete_subagent_child_worker(
            task=task,
            task_board=task_board,
            context=context,
            parent_execution=parent_execution,
            child_execution=None,
            status="succeeded" if succeeded else "failed",
            summary=summary_text,
            artifact_refs=[],
            validation_refs=validation_refs,
            failure_evidence_refs=failure_refs,
            child_plan_refs=child_plan_refs,
            model_calls=model_calls,
            tool_calls=tool_calls,
            evidence_path=context.run_dir / "worker_results.jsonl" if context.run_dir else None,
        )

    def _execute_one_readonly_fanout_child(
        self,
        *,
        child: dict,
        slot: WorkerExecutionSlot,
        task: dict,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
        parent_execution: dict,
        child_plan: dict,
        child_plan_refs: list[str],
    ) -> TaskExecutionSummary:
        child_task = self._readonly_fanout_task(task, child, parent_execution, child_plan)
        return self.worker_runner.run(
            task=child_task,
            context=context,
            runtime_context={
                **runtime_context,
                "current_worker_invocation_id": slot.worker_id,
                "current_worker_result_id": slot.result_id,
                "subagent_fanout_child": child,
                "subagent_worker": {
                    **dict(runtime_context.get("subagent_worker") or {}),
                    "worker_invocation_id": slot.worker_id,
                    "worker_result_id": slot.result_id,
                    "parent_worker_invocation_id": parent_execution.get("worker_invocation_id"),
                    "child_plan_refs": child_plan_refs,
                    "scheduling_strategy": child_plan.get("scheduling_strategy"),
                },
            },
            execute_task=lambda mounted_context: self._execute_readonly_fanout_child_once(
                task=child_task,
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
            worker_id=slot.worker_id,
            result_id=slot.result_id,
        )

    def _execute_readonly_fanout_child_once(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        coder: CoderAgent,
        goal_spec: dict,
        project_config: dict,
        runtime_context: dict,
    ) -> TaskExecutionSummary:
        available_tools = model_tools_available_for_task(
            self.registry.names(),
            task,
            allow_shell=self._shell_allowed(context.policy),
        )
        action = self._validation_probe_readonly_child_action(
            task=task,
            runtime_context=runtime_context,
            available_tools=available_tools,
        ) or coder.propose_action(
            task=task,
            goal_spec=goal_spec,
            project_config=project_config,
            available_tools=available_tools,
            run_id=context.run_id or "",
            runtime_context=runtime_context,
        )
        action = self.action_preparer.prepare(action, task, context.policy)
        self._enforce_readonly_fanout_action(task, action)
        tool_results = self.tool_gateway.run_tool_calls(
            action.get("tool_calls") or [], task, context
        )
        verification = list(action.get("verification") or [])
        verification_results = self.tool_gateway.run_tool_calls(
            verification,
            task,
            context,
            stop_on_failure=False,
            stop_verification_on_fatal=True,
        )
        validation_refs = self.evidence_sink.record_validation_results(
            context,
            task,
            verification,
            verification_results,
        )
        failed = [
            result
            for result in [*tool_results, *verification_results]
            if not bool(getattr(result, "ok", False))
        ]
        if failed:
            summary = "; ".join(str(getattr(result, "summary", "")) for result in failed)
            self.evidence_sink.record_task_failure(
                context,
                task,
                "readonly_fanout_child_failed",
                summary,
                tool_results=tool_results,
                verification_results=verification_results,
            )
            return TaskExecutionSummary(
                task_id=task["task_id"],
                status="blocked",
                summary=summary,
                tool_calls=len(tool_results),
                verification_calls=len(verification_results),
                evidence_path=(
                    context.run_dir / "task_failures.jsonl" if context.run_dir else None
                ),
                validation_refs=validation_refs,
            )
        return TaskExecutionSummary(
            task_id=task["task_id"],
            status="done",
            summary=str(
                action.get("completion_notes")
                or action.get("summary")
                or "readonly child completed"
            ),
            tool_calls=len(tool_results),
            verification_calls=len(verification_results),
            evidence_path=context.run_dir / "validation_results.jsonl" if context.run_dir else None,
            validation_refs=validation_refs,
        )

    def _validation_probe_readonly_child_action(
        self,
        *,
        task: dict,
        runtime_context: dict,
        available_tools: list[str],
    ) -> dict | None:
        hints = task.get("runtime_profile_hints")
        hints = hints if isinstance(hints, dict) else {}
        probe_ids = [str(item) for item in hints.get("validation_probe_ids") or [] if str(item)]
        if not probe_ids or not (
            {"readonly_fanout_succeeds", "readonly_write_tool_blocked"} & set(probe_ids)
        ):
            return None
        if not runtime_context.get("subagent_fanout_child"):
            return None
        if "readonly_write_tool_blocked" in probe_ids:
            return {
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": "Runtime-managed readonly write-gate validation probe.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "readonly_fanout_violation.txt",
                            "content": "must be blocked",
                            "overwrite": True,
                        },
                        "reason": "Probe that readonly fanout blocks write tools.",
                    }
                ],
                "verification": [],
                "runtime_requests": [],
                "completion_notes": "readonly write-gate probe attempted a write",
            }
        tool_names = set(available_tools)
        if "run_command" in tool_names:
            verification = [
                {
                    "tool_name": "run_command",
                    "args": {"command": 'python -c "assert True"'},
                    "reason": "Record readonly fanout child verification evidence.",
                }
            ]
        elif "read_file" in tool_names:
            verification = [
                {
                    "tool_name": "read_file",
                    "args": {"path": _readonly_probe_read_path(task)},
                    "reason": "Record readonly fanout child verification evidence.",
                }
            ]
        elif "list_files" in tool_names:
            verification = [
                {
                    "tool_name": "list_files",
                    "args": {"path": _readonly_probe_list_path(task)},
                    "reason": "Record readonly fanout child verification evidence.",
                }
            ]
        else:
            return None
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Runtime-managed readonly validation probe child verification.",
            "tool_calls": [],
            "verification": verification,
            "runtime_requests": [],
            "completion_notes": "readonly validation probe child completed",
        }

    def _enforce_readonly_fanout_action(self, task: dict, action: dict) -> None:
        write_tools = {"write_file", "apply_patch", "restore_backup"}
        for call in [
            *list(action.get("tool_calls") or []),
            *list(action.get("verification") or []),
        ]:
            if str(call.get("tool_name") or "") in write_tools:
                raise PermissionError(
                    f"Readonly fanout child cannot use write tool: {task['task_id']}"
                )

    def _readonly_fanout_task(
        self,
        parent_task: dict,
        child: dict,
        parent_execution: dict,
        child_plan: dict,
    ) -> dict:
        child_task_id = str(child.get("child_task_id") or parent_task["task_id"])
        hints = dict(parent_task.get("runtime_profile_hints") or {})
        hints.update(
            {
                "worker_kind": "subagent_readonly_child",
                "parent_task_id": parent_task.get("task_id"),
                "parent_worker_invocation_id": parent_execution.get("worker_invocation_id"),
                "parent_runtime_profile_id": parent_execution.get("runtime_profile_id"),
                "candidate_parent_execution_id": parent_execution.get("execution_id"),
            }
        )
        return {
            **parent_task,
            "task_id": child_task_id,
            "title": str(child.get("title") or parent_task.get("title") or child_task_id),
            "description": str(child.get("objective") or parent_task.get("description") or ""),
            "acceptance": list(child.get("acceptance") or []),
            "read_scope": list(child.get("read_scope") or parent_task.get("read_scope") or []),
            "write_scope": [],
            "expected_changed_files": [],
            "expected_artifacts": [],
            "allowed_tools": list(
                child.get("allowed_tools") or ["list_files", "read_file", "search_text"]
            ),
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": True,
                "allows_expected_failure": False,
            },
            "runtime_profile_hints": hints,
            "multi_agent_strategy": {
                "mode": "readonly_fanout_child",
                "max_child_workers": 1,
                "planner_child_plan": False,
                "coordination_policy": {
                    "write_allowed": False,
                    "requires_merge_gate": False,
                    "scale_out_parent_plan": child_plan.get("subagent_child_plan_id"),
                },
            },
        }

    def _reset_task_for_subagent_child_attempt(
        self,
        task_board: TaskBoard,
        task_id: str,
    ) -> None:
        try:
            status = str(task_board.get_task(task_id).get("status") or "")
            if status == "blocked":
                task_board.update_status(task_id, "ready")
                status = "ready"
            if status == "ready":
                task_board.update_status(task_id, "in_progress")
        except Exception:
            return

    def _complete_subagent_child_worker(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        parent_execution: dict,
        child_execution: dict | None,
        status: str,
        summary: str,
        artifact_refs: list[str],
        validation_refs: list[str],
        failure_evidence_refs: list[str],
        model_calls: int,
        tool_calls: int,
        child_plan_refs: list[str] | None = None,
        evidence_path: Path | None = None,
    ) -> tuple[TaskExecutionSummary, dict | None]:
        task_id = str(task["task_id"])
        worker_result = complete_subagent_worker_execution(
            run_dir=context.run_dir,
            validator=context.validator,
            execution_result=parent_execution,
            status=status,
            summary=summary,
            artifact_refs=artifact_refs,
            validation_refs=validation_refs,
            failure_evidence_refs=failure_evidence_refs,
            child_plan_refs=list(child_plan_refs or []),
            model_calls=model_calls,
            tool_calls=tool_calls,
        )
        payload = subagent_worker_observation_payload(parent_execution, worker_result or {})
        parent_observation = persist_agent_loop_observation_for_execution(
            run_dir=context.run_dir,
            validator=context.validator,
            execution_result=parent_execution,
            status=str(payload["status"]),
            summary=str(payload["summary"]),
            evidence_refs=list(payload["evidence_refs"]),
            next_recommended_action=str(payload["next_recommended_action"]),
        )
        if status != "succeeded":
            self._mark_task_blocked(task_board, task_id)
        self._record_progress(
            context,
            task,
            channel="execution_chain",
            event_type="message",
            phase="execute",
            status="completed" if status == "succeeded" else "blocked",
            title="Subagent worker completed",
            summary=summary,
            evidence_refs=failure_evidence_refs,
            transcript_kind="subagent_summary",
            ui_intent="work_progress" if status == "succeeded" else "needs_attention",
            data={
                "task_id": task_id,
                "parent_agent_loop_execution": parent_execution,
                "child_agent_loop_execution": child_execution or {},
                "child_plan_refs": list(child_plan_refs or []),
                "agent_loop_observation": parent_observation or {},
                "worker_result": worker_result or {},
            },
        )
        return (
            TaskExecutionSummary(
                task_id=task_id,
                status="done" if status == "succeeded" else "blocked",
                summary=summary,
                tool_calls=tool_calls,
                verification_calls=0,
                evidence_path=evidence_path
                or (
                    context.run_dir / "worker_results.jsonl"
                    if context.run_dir is not None
                    else None
                ),
                validation_refs=validation_refs,
            ),
            parent_observation,
        )

    def _attach_parent_worker_to_loop_decision(
        self,
        loop_decision: dict,
        runtime_context: dict,
    ) -> None:
        worker_id = str(runtime_context.get("current_worker_invocation_id") or "")
        if worker_id:
            loop_decision["parent_worker_invocation_id"] = worker_id
        result_id = str(runtime_context.get("current_worker_result_id") or "")
        if result_id:
            loop_decision["parent_worker_result_id"] = result_id
        runtime_profile_id = str(runtime_context.get("runtime_profile_id") or "")
        if runtime_profile_id:
            loop_decision["parent_runtime_profile_id"] = runtime_profile_id

    def _subagent_child_task(
        self,
        task: dict,
        parent_decision: dict,
        parent_execution: dict,
    ) -> dict:
        child = dict(task)
        next_action = parent_decision.get("next_action")
        next_action = next_action if isinstance(next_action, dict) else {}
        capability = next_action.get("capability_ref")
        capability = capability if isinstance(capability, dict) else {}
        expected = next_action.get("expected_observation")
        expected = expected if isinstance(expected, dict) else {}
        hints = dict(child.get("runtime_profile_hints") or {})
        hints.update(
            {
                "worker_kind": "subagent",
                "parent_task_id": task.get("task_id"),
                "parent_worker_invocation_id": parent_execution.get("worker_invocation_id"),
                "parent_runtime_profile_id": parent_execution.get("runtime_profile_id"),
                "candidate_parent_execution_id": parent_execution.get("execution_id"),
            }
        )
        child["runtime_profile_hints"] = hints
        child["role"] = str(capability.get("name") or task.get("role") or "CoderAgent")
        child["assigned_agent_id"] = str(capability.get("name") or child["role"])
        child["parallel_safety"] = str(
            expected.get("parallel_safety") or task.get("parallel_safety") or "serial"
        )
        child["context_requirements"] = self._subagent_context_requirements(task, expected)
        child["notes"] = (
            str(task.get("notes") or "")
            + f"\nSubagent delegated by {parent_decision.get('decision_id')} "
            f"for reason: {next_action.get('reason')}"
        ).strip()
        return child

    def _subagent_context_requirements(self, task: dict, expected: dict) -> dict:
        current = task.get("context_requirements")
        base = dict(current) if isinstance(current, dict) else {}
        return {
            **base,
            "mount_type": str(
                expected.get("mount_type") or base.get("mount_type") or "coding_context"
            ),
            "include_artifacts": bool(expected.get("include_artifacts", False)),
            "include_failures": bool(expected.get("include_failures", True)),
            "include_decisions": bool(expected.get("include_decisions", True)),
            "include_validation": bool(expected.get("include_validation", True)),
            "recent_event_count": int(expected.get("recent_event_count") or 5),
            "isolation_policy": "subagent_child_context",
        }

    def _subagent_child_runtime_context(
        self,
        runtime_context: dict,
        *,
        parent_decision: dict,
        parent_execution: dict,
    ) -> dict:
        child_context = dict(runtime_context)
        child_context["subagent_worker"] = {
            "worker_invocation_id": parent_execution.get("worker_invocation_id"),
            "worker_result_id": parent_execution.get("worker_result_id"),
            "parent_execution_id": parent_execution.get("execution_id"),
            "parent_decision_id": parent_decision.get("decision_id"),
            "runtime_profile_id": parent_execution.get("runtime_profile_id"),
            "parallel_model": "worker_slot_ready_serial_now_parallel_safe_later",
            "context_isolation": "subagent_child_context",
        }
        child_context["parent_agent_loop_decision"] = parent_decision
        child_context["parent_agent_loop_execution"] = parent_execution
        return child_context

    def _should_continue_subagent_child_loop(
        self,
        *,
        context: RuntimeContext,
        round_index: int,
        max_rounds: int,
        observation: dict | None,
    ) -> bool:
        if round_index >= max_rounds or not isinstance(observation, dict):
            return False
        if str(observation.get("status") or "") != "failed":
            return False
        if str(observation.get("next_recommended_action") or "") not in {"repair", "tool"}:
            return False
        if context.budget is None:
            return False
        pressure = BudgetController.pressure(context.policy, context.budget.cost_report())
        return str(pressure.get("status") or "") not in {"hard_stop", "exceeded"}

    def _should_continue_after_subagent(
        self,
        *,
        context: RuntimeContext,
        round_index: int,
        max_rounds: int,
        observation: dict | None,
    ) -> bool:
        if round_index >= max_rounds or not isinstance(observation, dict):
            return False
        if str(observation.get("status") or "") == "pending":
            return False
        if str(observation.get("next_recommended_action") or "") not in {
            "repair",
            "replan",
            "ask",
            "stop",
            "tool",
        }:
            return False
        if context.budget is None:
            return False
        pressure = BudgetController.pressure(context.policy, context.budget.cost_report())
        return str(pressure.get("status") or "") not in {"hard_stop", "exceeded"}

    def _handle_runtime_managed_loop_action(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        action_kind: str,
        round_index: int,
        max_rounds: int,
        latest_decision: dict | None,
        execution_result: dict | None,
        latest_summary: TaskExecutionSummary | None,
    ) -> TaskExecutionSummary | None:
        if action_kind not in {"subagent", "repair", "replan", "stop"}:
            return None
        task_id = str(task["task_id"])
        if action_kind == "stop":
            loop_observation = persist_agent_loop_observation_for_execution(
                run_dir=context.run_dir,
                validator=context.validator,
                execution_result=execution_result,
                status="stopped",
                summary="Model stopped the bounded agent loop.",
                next_recommended_action="stop",
            )
            self._record_progress(
                context,
                task,
                channel="execution_chain",
                event_type="message",
                phase="result",
                status="completed"
                if latest_summary and latest_summary.status == "done"
                else "blocked",
                title="Agent loop stopped",
                summary="Model selected stop after reviewing the latest observation.",
                transcript_kind="stop",
                ui_intent="result",
                data={
                    "task_id": task_id,
                    "agent_loop_execution_result": execution_result or {},
                    "agent_loop_observation": loop_observation or {},
                    "recommended_command": "status --debug",
                },
            )
            self._record_agent_loop_run_summary(
                context=context,
                task_id=task_id,
                status="completed"
                if latest_summary and latest_summary.status == "done"
                else "stopped",
                exit_reason="stop",
                rounds_completed=round_index,
                max_rounds=max_rounds,
                summary="Model selected stop after reviewing the latest observation.",
                recommended_command="status --debug",
                latest_decision=latest_decision,
                latest_execution=execution_result,
                latest_observation=loop_observation,
            )
            if latest_summary is not None:
                return latest_summary
            self._mark_task_blocked(task_board, task_id)
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary="Agent loop stopped before completing the task.",
                tool_calls=0,
                verification_calls=0,
                evidence_path=context.run_dir / "agent_loop_observations.jsonl"
                if context.run_dir is not None
                else None,
            )
        if action_kind == "subagent":
            self._mark_task_blocked(task_board, task_id)
            loop_observation = persist_agent_loop_observation_for_execution(
                run_dir=context.run_dir,
                validator=context.validator,
                execution_result=execution_result,
                status="pending",
                summary=(
                    "Subagent worker dispatch was recorded; Runtime is waiting for "
                    "worker completion or a recovery decision."
                ),
                next_recommended_action="subagent",
            )
            worker_id = (
                execution_result.get("worker_invocation_id")
                if isinstance(execution_result, dict)
                else None
            )
            summary = (
                "Subagent dispatch recorded"
                + (f" as {worker_id}." if worker_id else ".")
                + " Runtime is waiting for subagent worker evidence or recovery routing."
            )
            self._record_progress(
                context,
                task,
                channel="execution_chain",
                event_type="message",
                phase="execute",
                status="blocked",
                title="Subagent dispatch recorded",
                summary=summary,
                transcript_kind="subagent_summary",
                ui_intent="needs_attention",
                data={
                    "task_id": task_id,
                    "agent_loop_execution_result": execution_result or {},
                    "agent_loop_observation": loop_observation or {},
                    "recommended_command": "execute",
                },
            )
            self._record_agent_loop_run_summary(
                context=context,
                task_id=task_id,
                status="blocked",
                exit_reason="subagent_pending",
                rounds_completed=round_index,
                max_rounds=max_rounds,
                summary=summary,
                recommended_command="execute",
                latest_decision=latest_decision,
                latest_execution=execution_result,
                latest_observation=loop_observation,
            )
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary=summary,
                tool_calls=0,
                verification_calls=0,
                evidence_path=context.run_dir / "worker_results.jsonl"
                if context.run_dir is not None
                else None,
            )
        command = "debug" if action_kind == "repair" else "replan"
        self._mark_task_blocked(task_board, task_id)
        summary = f"Model selected `{action_kind}` after reviewing the latest observation."
        loop_observation = persist_agent_loop_observation_for_execution(
            run_dir=context.run_dir,
            validator=context.validator,
            execution_result=execution_result,
            status="pending",
            summary=summary,
            next_recommended_action=action_kind,
        )
        self._record_progress(
            context,
            task,
            channel="execution_chain",
            event_type="message",
            phase="execute",
            status="blocked",
            title=f"Agent loop requested {action_kind}",
            summary=summary,
            transcript_kind="repair" if action_kind == "repair" else "todo_update",
            ui_intent="needs_attention",
            data={
                "task_id": task_id,
                "agent_loop_execution_result": execution_result or {},
                "agent_loop_observation": loop_observation or {},
                "recommended_command": command,
            },
        )
        self._record_agent_loop_run_summary(
            context=context,
            task_id=task_id,
            status="blocked",
            exit_reason="repair_dispatch" if action_kind == "repair" else "replan_dispatch",
            rounds_completed=round_index,
            max_rounds=max_rounds,
            summary=summary,
            recommended_command=command,
            latest_decision=latest_decision,
            latest_execution=execution_result,
            latest_observation=loop_observation,
        )
        return TaskExecutionSummary(
            task_id=task_id,
            status="blocked",
            summary=summary,
            tool_calls=0,
            verification_calls=0,
            evidence_path=context.run_dir / "agent_loop_observations.jsonl"
            if context.run_dir is not None
            else None,
        )

    def _next_action_after_attempt(
        self,
        *,
        attempt_status: str,
        next_action: dict,
    ) -> str | None:
        expected = next_action.get("expected_observation")
        expected_observation = expected if isinstance(expected, dict) else {}
        requested = str(expected_observation.get("next_recommended_action") or "")
        if requested in {"tool", "subagent", "repair", "replan", "ask", "stop"}:
            return requested
        if expected_observation.get("requires_follow_up_decision") is True:
            return "stop"
        if attempt_status != "done" and expected_observation.get("auto_repair_on_failure") is True:
            return "repair"
        return None

    def _should_continue_agent_loop(
        self,
        *,
        context: RuntimeContext,
        round_index: int,
        max_rounds: int,
        observation: dict | None,
        next_action: dict,
        attempt_status: str,
    ) -> bool:
        if round_index >= max_rounds or not isinstance(observation, dict):
            return False
        if not self._loop_continuation_requested(
            next_action=next_action,
            attempt_status=attempt_status,
        ):
            return False
        observation_next_action = str(observation.get("next_recommended_action") or "")
        if observation_next_action not in {"tool", "repair", "replan", "stop"}:
            return False
        if context.budget is None:
            return False
        pressure = BudgetController.pressure(context.policy, context.budget.cost_report())
        return str(pressure.get("status") or "") not in {"hard_stop", "exceeded"}

    def _agent_loop_exit_reason_after_attempt(
        self,
        *,
        context: RuntimeContext,
        round_index: int,
        max_rounds: int,
        observation: dict | None,
        next_action: dict,
        attempt_status: str,
    ) -> tuple[str, str, str | None]:
        if attempt_status == "done":
            return ("completed", "completed", None)
        if not isinstance(observation, dict):
            return ("blocked", "tool_failed", "debug")
        requested = self._loop_continuation_requested(
            next_action=next_action,
            attempt_status=attempt_status,
        )
        observation_next_action = str(observation.get("next_recommended_action") or "")
        actionable = observation_next_action in {"tool", "repair", "replan", "stop"}
        if requested and actionable and context.budget is not None:
            pressure = BudgetController.pressure(context.policy, context.budget.cost_report())
            if str(pressure.get("status") or "") in {"hard_stop", "exceeded"}:
                return ("blocked", "budget_hard_stop", "compact")
        if requested and actionable and round_index >= max_rounds:
            return ("blocked", "max_rounds", "status --debug")
        return ("blocked", "tool_failed", "debug")

    def _record_agent_loop_run_summary(
        self,
        *,
        context: RuntimeContext,
        task_id: str,
        status: str,
        exit_reason: str,
        rounds_completed: int,
        max_rounds: int,
        summary: str,
        recommended_command: str | None,
        latest_decision: dict | None,
        latest_execution: dict | None,
        latest_observation: dict | None,
        evidence_refs: list[str] | None = None,
    ) -> dict | None:
        budget_state, context_pressure = self._agent_loop_summary_pressure(context)
        record = build_agent_loop_run_summary(
            run_id=context.run_id,
            task_id=task_id,
            status=status,
            exit_reason=exit_reason,
            rounds_completed=rounds_completed,
            max_rounds=max_rounds,
            summary=summary,
            recommended_command=recommended_command,
            latest_decision=latest_decision,
            latest_execution=latest_execution,
            latest_observation=latest_observation,
            evidence_refs=evidence_refs,
            budget=budget_state,
            context_pressure=context_pressure,
        )
        return persist_agent_loop_run_summary(
            run_dir=context.run_dir,
            validator=context.validator,
            summary=record,
        )

    def _agent_loop_summary_pressure(
        self,
        context: RuntimeContext,
    ) -> tuple[dict, dict]:
        if context.budget is None:
            return ({}, {})
        report = context.budget.cost_report()
        pressure = BudgetController.pressure(context.policy, report)
        budget_state = {
            "status": pressure.get("status"),
            "highest_label": pressure.get("highest_label"),
            "highest_ratio": pressure.get("highest_ratio"),
            "model_calls": report.get("model_calls", 0),
            "tool_calls": report.get("tool_calls", 0),
            "tool_budget_units": report.get("tool_budget_units", report.get("tool_calls", 0)),
            "repair_attempts": report.get("repair_attempts", 0),
            "warnings": list(report.get("warnings") or []),
        }
        context_pressure = {
            "status": report.get("context_pressure_status", "within_budget"),
            "context_window_ratio": report.get("context_window_ratio", 0.0),
            "context_window_tokens": report.get("context_window_tokens", 0),
            "latest_context_estimated_tokens": report.get("latest_context_estimated_tokens", 0),
            "max_context_estimated_tokens": report.get("max_context_estimated_tokens", 0),
            "context_compactions": report.get("context_compactions", 0),
            "duplicate_content_hash_count": len(report.get("context_duplicate_content_hashes") or []),
        }
        return (budget_state, context_pressure)

    def _loop_continuation_requested(self, *, next_action: dict, attempt_status: str) -> bool:
        expected = next_action.get("expected_observation")
        expected_observation = expected if isinstance(expected, dict) else {}
        requested = str(expected_observation.get("next_recommended_action") or "")
        if requested in {"tool", "repair", "replan", "stop"}:
            return True
        if expected_observation.get("requires_follow_up_decision") is True:
            return True
        return (
            attempt_status != "done" and expected_observation.get("auto_repair_on_failure") is True
        )

    def _mark_task_blocked(self, task_board: TaskBoard, task_id: str) -> None:
        task = task_board.get_task(task_id)
        if task.get("status") != "blocked":
            task_board.update_status(task_id, "blocked")

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
        gate = self.worker_recorder.delegation_gate(task)
        if gate["status"] == "blocked":
            return self._block_for_delegation_quality_gate(
                task=task,
                task_board=task_board,
                context=context,
                worker_slot=worker_slot,
                gate=gate,
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
                runtime_context={
                    **mounted_context,
                    "current_worker_invocation_id": worker_slot.worker_id,
                    "current_worker_result_id": worker_slot.result_id,
                },
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

    def _block_for_delegation_quality_gate(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        worker_slot: WorkerExecutionSlot,
        gate: dict,
    ) -> TaskExecutionSummary:
        blocked = self.blocking_handler.block_for_failure(
            context=context,
            task_board=task_board,
            task=task,
            reason=str(gate["reason"]),
            failure_type="delegation_brief_quality_gate",
            action={
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": str(gate["reason"]),
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "completion_notes": "Worker was denied before model execution.",
            },
        )
        timestamp = now_iso()
        self.worker_recorder.record_execution(
            context=context,
            worker_id=worker_slot.worker_id,
            result_id=worker_slot.result_id,
            task=task,
            status="denied",
            started_at=timestamp,
            ended_at=timestamp,
            model_calls=0,
            tool_calls=0,
            artifact_refs=[],
            validation_refs=[],
            failure_evidence_refs=self._refs(blocked.evidence_path),
            summary=str(gate["reason"]),
            runtime_profile_id=self.worker_recorder.default_runtime_profile_id(task),
            actor="ExecuteCommand",
        )
        self._record_progress(
            context,
            task,
            channel="evidence",
            event_type="evidence",
            phase="blocked",
            status="blocked",
            title="Worker brief needs attention",
            summary=str(gate["reason"]),
            evidence_refs=self._refs(blocked.evidence_path),
            transcript_kind="ask",
            ui_intent="needs_input",
            data={
                "task_id": task["task_id"],
                "failure_type": "delegation_brief_quality_gate",
                "delegation_gate": gate,
            },
        )
        return self._blocked_task_summary(blocked)

    def _validation_probe_runtime_action(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        round_index: int,
        latest_observation: dict | None,
    ) -> dict | None:
        hints = task.get("runtime_profile_hints")
        hints = hints if isinstance(hints, dict) else {}
        probe_ids = [str(item) for item in hints.get("validation_probe_ids") or [] if str(item)]
        if not probe_ids:
            return None
        if "repair_replan_path" in set(probe_ids):
            return self._repair_replan_probe_runtime_action(
                task=task,
                context=context,
                round_index=round_index,
                latest_observation=latest_observation,
            )
        if "ask_stop_path" in set(probe_ids):
            return self._ask_stop_probe_runtime_action(
                task=task,
                context=context,
                round_index=round_index,
                latest_observation=latest_observation,
            )
        if "context_pressure_path" in set(probe_ids):
            return self._context_pressure_probe_runtime_action(
                task=task,
                context=context,
                round_index=round_index,
                latest_observation=latest_observation,
            )
        if "capability_selection_path" in set(probe_ids):
            return self._capability_selection_probe_runtime_action(
                task=task,
                context=context,
                round_index=round_index,
                latest_observation=latest_observation,
            )
        if round_index != 1 or latest_observation:
            return None
        if hints.get("force_next_action") != "subagent":
            return None
        strategy = task.get("multi_agent_strategy")
        strategy = strategy if isinstance(strategy, dict) else {}
        expected_observation = {
            "summary": "runtime-managed validation probe subagent result",
            "validation_probe_ids": probe_ids,
            "parallel_safety": task.get("parallel_safety") or "readonly",
            "multi_agent_strategy": strategy,
            "read_scope": task.get("read_scope") or ["."],
            "write_scope": task.get("write_scope") or [],
            "allowed_tools": task.get("allowed_tools") or [],
            "acceptance": task.get("acceptance") or [],
            "success_signal": "validation probe evidence recorded",
        }
        sequence = (
            self._jsonl_count(context.run_dir / "agent_loop_decisions.jsonl") + 1
            if context.run_dir
            else 1
        )
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Runtime selected subagent path for a targeted validation probe.",
            "tool_calls": [],
            "verification": [],
            "runtime_requests": [],
            "completion_notes": "Runtime-managed validation probe dispatch.",
            "agent_loop_decision": {
                "schema_version": "0.1.0",
                "decision_id": f"agent-loop-decision-{sequence:04d}",
                "run_id": context.run_id or "",
                "task_id": task["task_id"],
                "created_at": now_iso(),
                "next_action": {
                    "action": "subagent",
                    "reason": "Targeted validation probe requires scheduler evidence.",
                    "target_task_id": task["task_id"],
                    "capability_ref": {"type": "subagent", "name": "CoderAgent"},
                    "expected_observation": expected_observation,
                    "risk": "medium",
                    "budget_hint": {"model_calls": 2, "tool_calls": 2},
                    "evidence_refs": [],
                },
            },
        }

    def _repair_replan_probe_runtime_action(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        round_index: int,
        latest_observation: dict | None,
    ) -> dict | None:
        sequence = (
            self._jsonl_count(context.run_dir / "agent_loop_decisions.jsonl") + 1
            if context.run_dir
            else 1
        )
        task_id = str(task["task_id"])
        if round_index == 1 and not latest_observation:
            return {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Runtime created a controlled failing tool action for repair validation.",
                "tool_calls": [],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": 'python -c "raise SystemExit(1)"',
                            "expected_returncodes": [0],
                        },
                        "reason": "Create a bounded failure observation for repair/replan validation.",
                    }
                ],
                "runtime_requests": [],
                "completion_notes": "Controlled failure should route into repair/replan.",
                "agent_loop_decision": {
                    "schema_version": "0.1.0",
                    "decision_id": f"agent-loop-decision-{sequence:04d}",
                    "run_id": context.run_id or "",
                    "task_id": task_id,
                    "created_at": now_iso(),
                    "next_action": {
                        "action": "tool",
                        "reason": "Targeted repair/replan probe needs a failed tool observation.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "run_command"},
                        "expected_observation": {
                            "summary": "Failed command should trigger repair/replan routing.",
                            "auto_repair_on_failure": True,
                        },
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 1},
                        "evidence_refs": [],
                    },
                },
            }
        if (
            round_index == 2
            and isinstance(latest_observation, dict)
            and str(latest_observation.get("status") or "") == "failed"
        ):
            observation_id = str(latest_observation.get("observation_id") or "")
            refs = [observation_id] if observation_id else []
            return {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Runtime routed the controlled failure into repair.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "completion_notes": "Repair dispatch evidence recorded.",
                "agent_loop_decision": {
                    "schema_version": "0.1.0",
                    "decision_id": f"agent-loop-decision-{sequence:04d}",
                    "run_id": context.run_id or "",
                    "task_id": task_id,
                    "created_at": now_iso(),
                    "next_action": {
                        "action": "repair",
                        "reason": "Controlled failed observation should enter debug repair.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "repair"},
                        "expected_observation": {
                            "summary": "Runtime records repair dispatch.",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": refs,
                    },
                },
            }
        return None

    def _ask_stop_probe_runtime_action(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        round_index: int,
        latest_observation: dict | None,
    ) -> dict | None:
        if round_index != 1 or latest_observation:
            return None
        sequence = (
            self._jsonl_count(context.run_dir / "agent_loop_decisions.jsonl") + 1
            if context.run_dir
            else 1
        )
        task_id = str(task["task_id"])
        return {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "summary": "Runtime stopped at an ask/stop validation boundary.",
            "tool_calls": [],
            "verification": [],
            "runtime_requests": [],
            "completion_notes": "Stop-report evidence should be recorded for ask/stop validation.",
            "agent_loop_decision": {
                "schema_version": "0.1.0",
                "decision_id": f"agent-loop-decision-{sequence:04d}",
                "run_id": context.run_id or "",
                "task_id": task_id,
                "created_at": now_iso(),
                "next_action": {
                    "action": "stop",
                    "reason": "Targeted ask/stop probe requires an explicit boundary instead of guessing.",
                    "target_task_id": task_id,
                    "capability_ref": {"type": "runtime", "name": "stop"},
                    "expected_observation": {
                        "summary": "Runtime records stop-report evidence.",
                    },
                    "risk": "low",
                    "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                    "evidence_refs": [],
                },
            },
        }

    def _context_pressure_probe_runtime_action(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        round_index: int,
        latest_observation: dict | None,
    ) -> dict | None:
        if round_index != 1 or latest_observation:
            return None
        pressure_ref = self._record_context_pressure_probe_snapshot(task, context)
        sequence = (
            self._jsonl_count(context.run_dir / "agent_loop_decisions.jsonl") + 1
            if context.run_dir
            else 1
        )
        task_id = str(task["task_id"])
        return {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "summary": "Runtime recorded context pressure evidence and stopped the probe.",
            "tool_calls": [],
            "verification": [],
            "runtime_requests": [],
            "completion_notes": "Context pressure snapshot evidence should be visible to validation.",
            "agent_loop_decision": {
                "schema_version": "0.1.0",
                "decision_id": f"agent-loop-decision-{sequence:04d}",
                "run_id": context.run_id or "",
                "task_id": task_id,
                "created_at": now_iso(),
                "next_action": {
                    "action": "stop",
                    "reason": "Targeted context pressure probe recorded compact-boundary evidence.",
                    "target_task_id": task_id,
                    "capability_ref": {"type": "runtime", "name": "stop"},
                    "expected_observation": {
                        "summary": "Runtime records stop after context pressure snapshot.",
                        "context_pressure_snapshot": pressure_ref,
                    },
                    "risk": "low",
                    "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                    "evidence_refs": [pressure_ref] if pressure_ref else [],
                },
            },
        }

    def _record_context_pressure_probe_snapshot(
        self,
        task: dict,
        context: RuntimeContext,
    ) -> str:
        if context.run_dir is None:
            return ""
        path = context.run_dir / "context_budget_snapshots.jsonl"
        store = JsonlStore(context.validator)
        existing = store.read_all(path, "context_budget_snapshot") if path.exists() else []
        snapshot_id = f"context-budget-snapshot-{len(existing) + 1:04d}"
        snapshot: dict[str, object] = {
            "schema_version": "0.1.0",
            "snapshot_id": snapshot_id,
            "run_id": context.run_id,
            "task_id": str(task["task_id"]),
            "created_at": now_iso(),
            "scope": "task_context",
            "runtime_profile_id": "runtime-profile-context-pressure-probe",
            "context_mount_id": "context-mount-context-pressure-probe",
            "worker_kind": "primary",
            "isolation_policy": "task_context",
            "parent_worker_invocation_id": None,
            "parent_runtime_profile_id": None,
            "estimated_tokens": 90000,
            "sections": {
                "goal_brief": 1200,
                "task_brief": 1800,
                "read_scope_files": 60000,
                "recent_events": 12000,
                "capability_registry": 15000,
            },
            "duplicate_content_hashes": [],
            "duplicate_estimated_tokens": 0,
            "duplicate_ref_count": 0,
            "context_window_tokens": 100000,
            "context_window_ratio": 0.9,
            "pressure_status": "hard_stop",
            "compaction_threshold": 0.75,
            "hard_stop_threshold": 0.9,
            "compact_boundary": {
                "status": "required",
                "recommended_action": "compact_before_next_child_round",
                "estimated_tokens_before": 90000,
                "estimated_duplicate_tokens": 0,
                "preserve_sections": ["goal_brief", "task_brief"],
                "droppable_sections": [
                    "read_scope_files",
                    "recent_events",
                    "capability_registry",
                ],
            },
            "evidence_refs": [],
        }
        store.append(path, snapshot, "context_budget_snapshot")
        return snapshot_id

    def _capability_selection_probe_runtime_action(
        self,
        *,
        task: dict,
        context: RuntimeContext,
        round_index: int,
        latest_observation: dict | None,
    ) -> dict | None:
        if round_index != 1 or latest_observation:
            return None
        refs = self._record_capability_selection_probe_evidence(task, context)
        sequence = (
            self._jsonl_count(context.run_dir / "agent_loop_decisions.jsonl") + 1
            if context.run_dir
            else 1
        )
        task_id = str(task["task_id"])
        return {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "summary": "Runtime recorded capability selection evidence and stopped the probe.",
            "tool_calls": [],
            "verification": [],
            "runtime_requests": [],
            "completion_notes": "Capability selection evidence should be visible to validation.",
            "agent_loop_decision": {
                "schema_version": "0.1.0",
                "decision_id": f"agent-loop-decision-{sequence:04d}",
                "run_id": context.run_id or "",
                "task_id": task_id,
                "created_at": now_iso(),
                "next_action": {
                    "action": "stop",
                    "reason": "Targeted capability selection probe recorded reasoned adapter evidence.",
                    "target_task_id": task_id,
                    "capability_ref": {"type": "runtime", "name": "stop"},
                    "expected_observation": {
                        "summary": "Runtime records stop after capability selection evidence.",
                    },
                    "risk": "low",
                    "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                    "evidence_refs": refs,
                },
            },
        }

    def _record_capability_selection_probe_evidence(
        self,
        task: dict,
        context: RuntimeContext,
    ) -> list[str]:
        if context.run_dir is None or context.run_id is None:
            return []
        store = JsonlStore(context.validator)
        decision = {
            "schema_version": "0.1.0",
            "capability_decision_id": "capability-decision-context-probe-0001",
            "run_id": context.run_id,
            "task_id": str(task["task_id"]),
            "tool_call_id": None,
            "capability_type": "mcp",
            "capability": "mcp:runtime_matrix/echo",
            "decision": {
                "decision": "allow",
                "reason": "Targeted capability selection probe chose MCP echo because it is catalog-visible and auditable.",
                "selected_capability_name": "runtime_matrix/echo",
                "alternatives_considered": ["tool:read_file", "skill:documents"],
                "evidence_refs": ["agent_loop_dispatch.json"],
            },
            "created_at": now_iso(),
        }
        mcp_invocation = {
            "schema_version": "0.1.0",
            "mcp_invocation_id": "mcp-invocation-context-probe-0001",
            "run_id": context.run_id,
            "task_id": str(task["task_id"]),
            "server": "runtime_matrix",
            "tool": "echo",
            "status": "skipped_runtime_probe",
            "capability_decision": decision["decision"],
            "created_at": now_iso(),
        }
        decisions_path = context.run_dir / "capability_decisions.jsonl"
        mcp_path = context.run_dir / "mcp_invocations.jsonl"
        store.append(decisions_path, decision)
        store.append(mcp_path, mcp_invocation)
        UserProgressLogger(context.run_dir / "user_progress.jsonl", context.validator).record(
            run_id=context.run_id,
            channel="evidence",
            event_type="evidence",
            phase="execute",
            status="completed",
            title="Capability selection evidence recorded",
            summary="Runtime recorded reasoned capability selection probe evidence.",
            display_level="inspector",
            evidence_refs=[str(decisions_path), str(mcp_path)],
            data={
                "task_id": str(task["task_id"]),
                "capability_type": "mcp",
                "capability_decision": decision,
            },
            call_chain=["ExecuteCommand", "capability_selection_probe"],
            execution_chain=[str(task["task_id"]), "mcp", "runtime_matrix/echo"],
        )
        return [str(decisions_path), str(mcp_path)]

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
                    "available_tools": model_tools_available_for_task(
                        self.registry.names(),
                        task,
                        allow_shell=self._shell_allowed(context.policy),
                    ),
                },
            )
            task_model_surface = model_tool_surface_for_task(
                self.registry.names(),
                task,
                allow_shell=self._shell_allowed(context.policy),
            )
            runtime_context["model_tool_surface"] = task_model_surface
            available_tools = model_tools_available_for_task(
                self.registry.names(),
                task,
                allow_shell=self._shell_allowed(context.policy),
            )
            max_rounds = self._agent_loop_max_rounds(context.policy)
            latest_loop_observation: dict | None = None
            latest_summary: TaskExecutionSummary | None = None
            for round_index in range(1, max_rounds + 1):
                self._refresh_harness_observations(runtime_context, context)
                runtime_context["agent_loop_round"] = {
                    "index": round_index,
                    "max_rounds": max_rounds,
                    "latest_observation": latest_loop_observation or {},
                }
                if latest_loop_observation:
                    runtime_context["latest_agent_loop_observation"] = latest_loop_observation
                action = self._validation_probe_runtime_action(
                    task=task,
                    context=context,
                    round_index=round_index,
                    latest_observation=latest_loop_observation,
                ) or coder.propose_action(
                    task=task,
                    goal_spec=goal_spec,
                    project_config=project_config,
                    available_tools=available_tools,
                    run_id=context.run_id or "",
                    runtime_context=runtime_context,
                )
                action = self.action_preparer.prepare(
                    action,
                    task,
                    context.policy,
                    round_index=round_index,
                )
                runtime_requests = list(action.get("runtime_requests") or [])
                loop_decision = action.get("agent_loop_decision")
                loop_execution_result = None
                if isinstance(loop_decision, dict):
                    self._attach_parent_worker_to_loop_decision(loop_decision, runtime_context)
                    persist_agent_loop_decision(
                        run_dir=context.run_dir,
                        validator=context.validator,
                        decision=loop_decision,
                    )
                    loop_execution_result = persist_agent_loop_execution_result(
                        run_dir=context.run_dir,
                        validator=context.validator,
                        decision=loop_decision,
                        create_decision_point=not runtime_requests,
                    )
                tool_calls = list(action.get("tool_calls") or [])
                verification = list(action.get("verification") or [])
                next_action = (
                    loop_decision.get("next_action", {}) if isinstance(loop_decision, dict) else {}
                )
                next_action_kind = str(next_action.get("action") or "")
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="message",
                    phase="execute",
                    status="running",
                    title="Worker action proposed",
                    summary=(
                        f"Round {round_index}/{max_rounds}: prepared {len(tool_calls)} "
                        f"tool call(s), {len(verification)} verification step(s), "
                        f"and {len(runtime_requests)} runtime request(s)."
                    ),
                    display_level="inspector",
                    data={
                        "task_id": task_id,
                        "agent_loop_round": round_index,
                        "agent_loop_max_rounds": max_rounds,
                        "tool_call_count": len(tool_calls),
                        "verification_count": len(verification),
                        "runtime_request_count": len(runtime_requests),
                        "summary": action.get("summary", ""),
                        "agent_loop_decision": loop_decision or {},
                        "recommended_command": recommended_command_for_next_action(next_action),
                        "agent_loop_execution_result": loop_execution_result or {},
                        "latest_agent_loop_observation": latest_loop_observation or {},
                        "model_tool_surface": task_model_surface,
                        "model_tool_calls": self._model_tool_call_summary(tool_calls, verification),
                    },
                )
                if next_action_kind == "subagent":
                    child_summary, latest_loop_observation = self._execute_subagent_child_loop(
                        task=task,
                        task_board=task_board,
                        context=context,
                        coder=coder,
                        goal_spec=goal_spec,
                        project_config=project_config,
                        runtime_context=runtime_context,
                        available_tools=available_tools,
                        parent_decision=loop_decision if isinstance(loop_decision, dict) else None,
                        parent_execution=loop_execution_result,
                    )
                    latest_summary = child_summary
                    continue_after_subagent = (
                        False
                        if _is_runtime_managed_validation_probe(task)
                        else self._should_continue_after_subagent(
                            context=context,
                            round_index=round_index,
                            max_rounds=max_rounds,
                            observation=latest_loop_observation,
                        )
                    )
                    if not continue_after_subagent:
                        status = "completed" if child_summary.status == "done" else "blocked"
                        exit_reason = (
                            "completed" if child_summary.status == "done" else "tool_failed"
                        )
                        recommended = (
                            recommended_command_for_next_action(
                                {"action": latest_loop_observation.get("next_recommended_action")}
                            )
                            if isinstance(latest_loop_observation, dict)
                            else "status --debug"
                        )
                        self._record_agent_loop_run_summary(
                            context=context,
                            task_id=task_id,
                            status=status,
                            exit_reason=exit_reason,
                            rounds_completed=round_index,
                            max_rounds=max_rounds,
                            summary=child_summary.summary,
                            recommended_command=recommended or "status --debug",
                            latest_decision=loop_decision
                            if isinstance(loop_decision, dict)
                            else None,
                            latest_execution=loop_execution_result,
                            latest_observation=latest_loop_observation,
                            evidence_refs=self._refs(child_summary.evidence_path)
                            + child_summary.validation_refs,
                        )
                        return child_summary
                    continue
                runtime_managed = self._handle_runtime_managed_loop_action(
                    task=task,
                    task_board=task_board,
                    context=context,
                    action_kind=next_action_kind,
                    round_index=round_index,
                    max_rounds=max_rounds,
                    latest_decision=loop_decision if isinstance(loop_decision, dict) else None,
                    execution_result=loop_execution_result,
                    latest_summary=latest_summary,
                )
                if runtime_managed is not None:
                    return runtime_managed
                runtime_request_result = self.runtime_request_policy.handle_runtime_requests(
                    action=action,
                    task=task,
                    task_board=task_board,
                    context=context,
                )
                if runtime_request_result is not None:
                    loop_observation = persist_agent_loop_observation_for_execution(
                        run_dir=context.run_dir,
                        validator=context.validator,
                        execution_result=loop_execution_result,
                        status="waiting_user",
                        summary=runtime_request_result.summary,
                        evidence_refs=self._refs(runtime_request_result.evidence_path),
                        next_recommended_action="ask",
                    )
                    self._record_agent_loop_run_summary(
                        context=context,
                        task_id=task_id,
                        status="waiting_user",
                        exit_reason="ask",
                        rounds_completed=round_index,
                        max_rounds=max_rounds,
                        summary=runtime_request_result.summary,
                        recommended_command="decide --list",
                        latest_decision=loop_decision if isinstance(loop_decision, dict) else None,
                        latest_execution=loop_execution_result,
                        latest_observation=loop_observation,
                        evidence_refs=self._refs(runtime_request_result.evidence_path),
                    )
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
                    loop_observation = persist_agent_loop_observation_for_execution(
                        run_dir=context.run_dir,
                        validator=context.validator,
                        execution_result=loop_execution_result,
                        status="blocked",
                        summary=blocked.summary,
                        evidence_refs=self._refs(blocked.evidence_path),
                        next_recommended_action="ask",
                    )
                    self._record_agent_loop_run_summary(
                        context=context,
                        task_id=task_id,
                        status="waiting_user",
                        exit_reason="ask",
                        rounds_completed=round_index,
                        max_rounds=max_rounds,
                        summary=blocked.summary,
                        recommended_command="decide --list",
                        latest_decision=loop_decision if isinstance(loop_decision, dict) else None,
                        latest_execution=loop_execution_result,
                        latest_observation=loop_observation,
                        evidence_refs=self._refs(blocked.evidence_path),
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
                        transcript_kind="ask",
                        ui_intent="needs_input",
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
                latest_loop_observation = persist_agent_loop_observation_for_execution(
                    run_dir=context.run_dir,
                    validator=context.validator,
                    execution_result=loop_execution_result,
                    status="succeeded" if attempt.status == "done" else "failed",
                    summary=attempt.summary,
                    evidence_refs=self._refs(attempt.evidence_path) + attempt.validation_refs,
                    next_recommended_action=self._next_action_after_attempt(
                        attempt_status=attempt.status,
                        next_action=next_action,
                    ),
                )
                latest_summary = TaskExecutionSummary(
                    task_id=attempt.task_id,
                    status=attempt.status,
                    summary=attempt.summary,
                    tool_calls=attempt.tool_calls,
                    verification_calls=attempt.verification_calls,
                    evidence_path=attempt.evidence_path,
                    validation_refs=attempt.validation_refs,
                )
                if not self._should_continue_agent_loop(
                    context=context,
                    round_index=round_index,
                    max_rounds=max_rounds,
                    observation=latest_loop_observation,
                    next_action=next_action,
                    attempt_status=attempt.status,
                ):
                    status, exit_reason, recommended = self._agent_loop_exit_reason_after_attempt(
                        context=context,
                        round_index=round_index,
                        max_rounds=max_rounds,
                        observation=latest_loop_observation,
                        next_action=next_action,
                        attempt_status=attempt.status,
                    )
                    self._record_agent_loop_run_summary(
                        context=context,
                        task_id=task_id,
                        status=status,
                        exit_reason=exit_reason,
                        rounds_completed=round_index,
                        max_rounds=max_rounds,
                        summary=attempt.summary,
                        recommended_command=recommended,
                        latest_decision=loop_decision if isinstance(loop_decision, dict) else None,
                        latest_execution=loop_execution_result,
                        latest_observation=latest_loop_observation,
                        evidence_refs=self._refs(attempt.evidence_path) + attempt.validation_refs,
                    )
                    return latest_summary
            if latest_summary is not None:
                self._record_agent_loop_run_summary(
                    context=context,
                    task_id=task_id,
                    status="blocked" if latest_summary.status != "done" else "completed",
                    exit_reason="max_rounds",
                    rounds_completed=max_rounds,
                    max_rounds=max_rounds,
                    summary=latest_summary.summary,
                    recommended_command="status --debug",
                    latest_decision=None,
                    latest_execution=None,
                    latest_observation=latest_loop_observation,
                    evidence_refs=self._refs(latest_summary.evidence_path)
                    + latest_summary.validation_refs,
                )
                return latest_summary
            self._record_agent_loop_run_summary(
                context=context,
                task_id=task_id,
                status="blocked",
                exit_reason="no_action",
                rounds_completed=max_rounds,
                max_rounds=max_rounds,
                summary="Agent loop stopped without executable model action.",
                recommended_command="status --debug",
                latest_decision=None,
                latest_execution=None,
                latest_observation=latest_loop_observation,
            )
            return TaskExecutionSummary(
                task_id=task_id,
                status="blocked",
                summary="Agent loop stopped without executable model action.",
                tool_calls=0,
                verification_calls=0,
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
                transcript_kind="ask",
                ui_intent="needs_input",
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
                transcript_kind="repair",
                ui_intent="needs_attention",
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
        raw_observations = load_raw_tool_observations(context.run_dir)
        if raw_observations:
            runtime_context["tool_observations"] = raw_observations

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
            transcript_kind="ask",
            ui_intent="needs_input",
            data={
                "task_id": result.task_id,
                "status": result.status,
                "permission_preview": result.permission_preview,
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
        display_level: str = "main",
        transcript_kind: str | None = None,
        ui_intent: str | None = None,
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
            display_level=display_level,
            evidence_refs=evidence_refs or [],
            transcript_kind=transcript_kind,
            ui_intent=ui_intent,
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
        model_failure = classify_model_failure(str(exc))
        if model_failure in {"network", "timeout", "rate_limited", "server_error"}:
            return f"provider_{model_failure}"
        if model_failure in {"configuration", "authentication", "budget"}:
            return f"provider_{model_failure}"
        return "exception"

    def _shell_allowed(self, policy: dict) -> bool:
        permission = str(policy.get("permission_mode") or "").lower()
        return permission in {"reviewed_auto", "allow", "allow_all", "trusted"}

    def _model_tool_call_summary(
        self,
        tool_calls: list[dict],
        verification: list[dict],
    ) -> list[dict]:
        summary = []
        for call in [*tool_calls, *verification]:
            if not isinstance(call, dict):
                continue
            summary.append(
                {
                    "tool_name": call.get("tool_name"),
                    "model_tool_name": call.get("model_tool_name") or call.get("tool_name"),
                    "tool_surface_adapter": call.get("tool_surface_adapter"),
                }
            )
        return summary

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


def _readonly_probe_read_path(task: dict) -> str:
    for path in task.get("read_scope") or []:
        text = str(path)
        if text and not text.endswith(("/", "\\")):
            return text
    return "AGENTS.md"


def _readonly_probe_list_path(task: dict) -> str:
    for path in task.get("read_scope") or []:
        text = str(path)
        if text.endswith(("/", "\\")):
            return text.rstrip("/\\") or "."
    return "src"


def _is_runtime_managed_validation_probe(task: dict) -> bool:
    hints = task.get("runtime_profile_hints")
    return isinstance(hints, dict) and hints.get("runtime_managed_validation_probe") is True
