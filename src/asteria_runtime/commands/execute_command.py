from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.budget import (
    BudgetController,
    resolve_budget_limits,
)
from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.context_prompt_view import context_prompt_view
from asteria_runtime.core.expert_registry import expert_roles, resolve_expert
from asteria_runtime.core.worker_executor import SubagentRequest, resolve_worker_executor
from asteria_runtime.core.model_driven_turn import (
    TurnControl,
    TurnEvent,
    run_model_driven_turn,
)
from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.core.agent_harness import load_harness_observations, load_raw_tool_observations
from asteria_runtime.core.agent_loop_run_summary import (
    build_agent_loop_run_summary,
    persist_agent_loop_run_summary,
)
from asteria_runtime.core.agent_tool_surface import (
    mcp_model_tools,
    model_tool_surface_for_task,
    model_tools_available_for_task,
    skill_model_tools,
)
from asteria_runtime.core.mcp_adapter import (
    McpAdapter,
    mcp_adapter_config_from_policy,
)
from asteria_runtime.core.skill_adapter import SkillAdapter, SkillRoot
from asteria_runtime.core.execution_coordinator import ExecutionCoordinator
from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.plugin_manifest import PluginManifestLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.core.run_state_finalizer import RunStateFinalizer
from asteria_runtime.core.run_config import effective_policy_for_run
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookDecision, RuntimeHookManager
from asteria_runtime.core.runtime_policy import (
    RuntimeRequestPolicy,
    RuntimeRequestPolicyResult,
    ToolPermissionDenied,
    ToolPermissionPolicy,
)
from asteria_runtime.core.task_blocking_handler import BlockingResult, TaskBlockingHandler
from asteria_runtime.core.task_attempt_runner import TaskAttemptRunner
from asteria_runtime.core.fast_path_policy import classify_fast_path
from asteria_runtime.core.task_contract import check_completion_contract
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
        # Methodology control hooks — the deterministic glue that keeps the model-driven loop working
        # systematically (kickoff reminder + stop-guardrail continuity). Boundary, not cognition;
        # they only fire on the model-driven loop's control hook points (task/turn_start/pre_final).
        self.hook_manager.register_control_handler(_methodology_turn_start_decision)
        self.hook_manager.register_control_handler(_methodology_stop_guardrail_decision)
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
        # MCP adapter is built lazily once policy is known (see _wire_mcp_adapter in run()).
        self.mcp_adapter: McpAdapter | None = None
        self.mcp_discovered_tools: list[dict] = []
        # Skill adapter (instruction/procedure capabilities) is likewise built lazily in run().
        self.skill_adapter: SkillAdapter | None = None
        self.skill_discovered: list[dict] = []

    def _wire_skill_adapter(self, policy: dict) -> None:
        """Discover skills (bundled + global ~/.asteria + workspace) and inject the body handler.

        No-op when no skill root exists. Skills are filesystem-only (no sessions to close);
        _reset_skill_adapter just drops the gateway reference at finalize. Workspace skills win
        over global/bundled on name collision (SkillDiscovery scope precedence).
        """
        self._reset_skill_adapter()
        roots: list[SkillRoot] = []
        bundled = Path(__file__).resolve().parents[1] / "skills" / "bundled"
        if bundled.exists():
            roots.append(SkillRoot(path=bundled, scope="global"))
        global_skills = Path.home() / ".asteria" / "skills"
        if global_skills.exists():
            roots.append(SkillRoot(path=global_skills, scope="global"))
        workspace_skills = self.root / ".asteria" / "skills"
        if workspace_skills.exists():
            roots.append(SkillRoot(path=workspace_skills, scope="workspace"))
        if not roots:
            return
        adapter = SkillAdapter.from_skill_roots(roots, handler="body")
        if not adapter.handlers:
            return
        self.skill_adapter = adapter
        self.tool_gateway = replace(self.tool_gateway, skill_adapter=adapter)
        try:
            self.skill_discovered = adapter.discover_skills()
        except Exception:  # noqa: BLE001 - discovery must never abort the run
            self.skill_discovered = []

    def _reset_skill_adapter(self) -> None:
        self.skill_adapter = None
        self.skill_discovered = []
        self.tool_gateway = replace(self.tool_gateway, skill_adapter=None)

    def _wire_mcp_adapter(self, policy: dict) -> None:
        """Build the MCP adapter from policy and inject it into the tool gateway.

        No-op when no MCP servers are configured (the default), so a run without MCP is
        unchanged. When servers are configured, the adapter's stdio sessions are opened here,
        tools are discovered for the model surface, and the adapter is injected into the
        (frozen) gateway via dataclasses.replace. Closing any prior adapter first bounds the
        leak if a previous run raised before _close_mcp_adapter ran.
        """
        self._close_mcp_adapter()
        self.mcp_discovered_tools = []
        config = mcp_adapter_config_from_policy(policy, root=self.root)
        if not config.servers:
            return
        adapter = McpAdapter.from_adapter_config(config)
        self.mcp_adapter = adapter
        self.tool_gateway = replace(self.tool_gateway, mcp_adapter=adapter)
        try:
            self.mcp_discovered_tools = adapter.discover_tools()
        except Exception:  # noqa: BLE001 - discovery must never abort the run
            self.mcp_discovered_tools = []

    def _close_mcp_adapter(self) -> None:
        adapter = getattr(self, "mcp_adapter", None)
        if adapter is not None:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self.mcp_adapter = None
        self.tool_gateway = replace(self.tool_gateway, mcp_adapter=None)

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

        self._wire_mcp_adapter(policy)
        self._wire_skill_adapter(policy)
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
        self._close_mcp_adapter()
        self._reset_skill_adapter()

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

    def _auto_repair_enabled(self, policy: dict) -> bool:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("auto_repair", False))

    def _max_repair_attempts_per_task(self, policy: dict) -> int:
        budgets = resolve_budget_limits(policy)
        try:
            value = int(budgets.get("max_repair_attempts_per_task") or 0)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _auto_replan_enabled(self, policy: dict) -> bool:
        # S79 second ring: close the task-level replan loop (model re-approaches THIS task within
        # the same goal scope). Default off — behaviour is byte-identical to today when disabled.
        # Goal-level replan (ReplanCommand: new-task synthesis / lineage) stays human-gated.
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("auto_replan", False))

    def _max_replans_per_task(self, policy: dict) -> int:
        budgets = resolve_budget_limits(policy)
        try:
            value = int(budgets.get("max_replans_per_task") or 0)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)


    def _loop_quality_guard_config(self, policy: dict) -> dict | None:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        guard = agent_loop.get("loop_quality_guard")
        return guard if isinstance(guard, dict) else None






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
            "repair_attempts_limit": self._max_repair_attempts_per_task(context.policy),
            "auto_repair_enabled": self._auto_repair_enabled(context.policy),
            "replan_attempts_limit": self._max_replans_per_task(context.policy),
            "auto_replan_enabled": self._auto_replan_enabled(context.policy),
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


    def _max_subagent_depth(self, policy: dict) -> int:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        try:
            value = int(agent_loop.get("max_subagent_depth") or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, value)

    def _subagent_backend_kind(self, policy: dict) -> str:
        """Which worker backend runs spawned experts: "local" (default, in-process) or the
        "cloud_session" stub (North Star, opt-in). Off by default → zero effect on local/offline."""
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return str(agent_loop.get("subagent_backend") or "local")

    def _subagent_allowed_tools(self, task: dict, expert: Any) -> list[str]:
        """The child expert's tool surface: the parent's allowed_tools, minus write tools for a
        read-only expert (reviewer / researcher)."""
        allowed = [str(item) for item in (task.get("allowed_tools") or [])]
        if not getattr(expert, "read_only", False):
            return allowed
        write_tools = {"write_file", "apply_patch", "edit_file", "restore_backup"}
        return [name for name in allowed if name not in write_tools]

    def _run_model_driven_task(
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
    ) -> TaskExecutionSummary:
        """立真身 gray path (ADR-0016 §1): run the task on the model-driven single loop.

        The model drives itself — each step it calls whatever tools it needs through the *real*
        ``ToolExecutionGateway`` (permissions / sandbox / evidence intact), reads the observations,
        and decides the next step. The loop's only control branch is "did the model call a tool or
        stop"; tool/command failures are fed back as observations rather than routed into an
        ``if next_action_kind == "repair"`` FSM branch. ``max_iterations`` is a resumable budget
        fuse, not cognition. Writes land directly in the workspace (non-parallel default), so this
        path finalizes the task_board + run summary itself rather than going through the FSM's
        candidate-promotion attempt runner. Gated by ``agent_loop.model_driven_turn`` (default off).
        """
        task_id = task["task_id"]
        # max_iterations is a fuse (budget boundary), NOT the FSM's cognitive round ceiling. Give the
        # model a little more headroom than the FSM's per-task rounds so a genuine multi-step task can
        # finish; the hard budget/hard-stop still governs cost.
        max_iterations = self._agent_loop_max_rounds(context.policy) + 4
        system_prompt, user_prompt = self._model_driven_prompts(
            task, goal_spec, project_config, available_tools, runtime_context, can_delegate=True
        )
        model_tier = str(runtime_context.get("execution_model_tier") or "strong")
        max_subagent_depth = self._max_subagent_depth(context.policy)
        subagent_counter = {"n": 0}

        # Methodology glue: the control hooks (kickoff reminder + stop-guardrail) run through the
        # RuntimeHookManager so they are policy-gated and audited like any hook. The loop consults
        # this callback at turn_start / pre_final and honours the returned TurnControl (boundary only).
        skill_names = [str(item["name"]) for item in self._methodology_skills(runtime_context)]
        expected_artifacts = [
            str(item)
            for item in (task.get("expected_artifacts") or task.get("write_scope") or [])
            if item
        ]

        def _hook(event_name: str, payload: dict) -> TurnControl:
            decision = self.hook_manager.dispatch_control(
                context,
                event_name,
                "execute",
                "ModelDrivenTurn",
                f"{event_name} control hook",
                task=task,
                data={
                    "iteration": payload.get("iteration"),
                    "model_tier": model_tier,
                    "root": str(context.root),
                    "expected_artifacts": expected_artifacts,
                    "methodology_skill_names": skill_names,
                },
            )
            return TurnControl(
                additional_context=decision.additional_context,
                continue_turn=decision.continue_turn,
            )

        def _spawn_subagent(args: dict) -> _SubagentResult:
            # Expert-cluster delegation (ADR-0022): the lead model routes a scoped sub-task to a
            # specialist. The child runs its OWN bounded 立真身 loop (fresh context, expert persona +
            # methodology skills, scoped tools) and returns ONLY a summary. Skeleton = serial, shared
            # workspace; concurrency + candidate isolation is Part B (B1). Depth-guarded so a child
            # cannot recurse without bound.
            depth = int(runtime_context.get("subagent_recursion_depth") or 0)
            if depth >= max_subagent_depth:
                return _SubagentResult(
                    ok=False,
                    status="failure",
                    error="subagent_recursion_depth_exceeded",
                    summary=(
                        f"spawn_subagent refused: recursion depth {depth} >= cap {max_subagent_depth}."
                    ),
                )
            expert = resolve_expert(args.get("role"))
            subagent_counter["n"] += 1
            child_task_id = f"{task_id}-sub-{subagent_counter['n']:02d}"
            child_allowed = self._subagent_allowed_tools(task, expert)
            child_task = {
                "task_id": child_task_id,
                "title": f"{expert.role} subagent",
                "description": str(args.get("task") or ""),
                "allowed_tools": child_allowed,
                "read_scope": [
                    str(item) for item in (args.get("read_scope") or task.get("read_scope") or []) if item
                ],
                "write_scope": (
                    []
                    if expert.read_only
                    else [str(item) for item in (args.get("write_scope") or []) if item]
                ),
                "expected_artifacts": [
                    str(item) for item in (args.get("expected_artifacts") or []) if item
                ],
            }
            child_runtime_context = {
                **runtime_context,
                "subagent_recursion_depth": depth + 1,
                "subagent_role": expert.role,
            }
            child_system, child_user = self._model_driven_prompts(
                child_task, goal_spec, project_config, child_allowed, child_runtime_context
            )
            child_system = f"{child_system}\n\n[Expert role: {expert.role}] {expert.persona}"
            # Pluggable worker backend: LocalExecutor (in-process, default) runs the child 立真身 loop
            # exactly as before; CloudSessionExecutor is an opt-in North Star stub. spawn_subagent
            # only describes the sub-task — where it runs is resolved here (bare gateway: the child
            # does not nest-spawn in this skeleton; concurrency + isolation is Part B).
            executor = resolve_worker_executor(
                self._subagent_backend_kind(context.policy), validator=self.validator
            )
            outcome = executor.run_subagent(
                SubagentRequest(
                    role=expert.role,
                    task=child_task,
                    system_prompt=child_system,
                    user_prompt=child_user,
                    available_tools=child_allowed,
                    model_tier=expert.model_tier,
                    max_iterations=max_iterations,
                ),
                model_client=coder.model_client,
                tool_runner=self.tool_gateway,
                context=context,
                on_event=lambda event: self._record_model_driven_event(context, child_task, event),
            )
            return _SubagentResult(
                ok=outcome.ok,
                status="success" if outcome.ok else "failure",
                summary=f"[{expert.role}] {outcome.summary}",
                data={
                    "role": expert.role,
                    "child_task_id": child_task_id,
                    "iterations": outcome.iterations,
                    "child_status": outcome.status,
                    "backend": outcome.data.get("backend"),
                    # Delegated artifacts flow up so the lead's completion contract credits them
                    # (observation_from_tool_result → _artifact_refs reads data["changed_files"]).
                    "changed_files": list(outcome.data.get("changed_files") or []),
                },
            )

        tool_runner = _SubagentAwareToolRunner(self.tool_gateway, _spawn_subagent)

        def _approval_gate(calls: list[dict]) -> dict | None:
            # 人审边界（ADR-0016）：把模型这一步要跑的整批工具当作一个待审动作，交给与 FSM 同一套
            # 执行策略去判定——命中 shell denylist 且尚无 approve_once 决策就生成一个 execution_policy_
            # approval DecisionPoint（已在案则返回 None）。策略/决策归 harness，脊梁循环只在执行边界拦。
            return self.tool_permission_policy.create_policy_decision_if_needed(
                action={"tool_calls": list(calls), "verification": []},
                task=task,
                context=context,
            )

        result = run_model_driven_turn(
            model_client=coder.model_client,
            tool_runner=tool_runner,
            task=task,
            context=context,
            available_tools=available_tools,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_tier=model_tier,
            max_iterations=max_iterations,
            transport="json",
            on_event=lambda event: self._record_model_driven_event(context, task, event),
            hook=_hook,
            approval_gate=_approval_gate,
        )

        # 人审边界命中（ADR-0016：人审=显式边界）：脊梁在跑到需人批的工具批前整批停手，本轮无残留
        # 写入。复用 FSM 同一套 block/证据/进度落法（单一真源），把任务标 blocked 并留下 pending
        # DecisionPoint —— run 层据 pending_decisions 把整个 run 报成 paused。人批后 resume 重跑本任务，
        # gate 认到 approval 便放行整批。
        if result.status == "paused" and result.pending_decision is not None:
            return self._pause_model_driven_task(
                task=task,
                task_board=task_board,
                context=context,
                decision=result.pending_decision,
                rounds_completed=result.iterations,
                max_rounds=max_iterations,
            )

        # 立真身完成判定 = 确定性正确性边界（ADR-0016：认知归模型、证据边界归 harness）。模型吐
        # done 只是它的认知；工件到底改没改、验证跑没跑 / 过没过，由 harness 用与 FSM 同一套
        # task_contract 复核（不重造轮子）。契约不满足即 blocked——正如预算保险丝覆盖上报状态，这是
        # 边界对"完成"的确定性否决，不替模型做认知（模型仍在循环内自行 repair，越权/超预算才被拦）。
        observations = result.observations
        # 改动工件来自成功观察的 artifact_refs（write_file→[path]，其余工具→data.changed_files）；
        # 脊梁的 _execute 不填 file_changes，artifact_refs 才是真源。失败/被拒的写不计入改动。
        changed_files = [
            str(ref)
            for obs in observations
            if getattr(obs, "ok", False)
            for ref in getattr(obs, "artifact_refs", [])
            if ref
        ]
        # 验证证据口径与 review 的确定性快评保持一致(单一真源语义):仅 bug_fix/single_file_bugfix
        # 要求可执行命令验证,其余(含 doc_update)读回产物即算验证。用同一 classify_fast_path 判定,
        # 避免执行门与评审门对"何为验证"各执一词。
        fast_path = classify_fast_path(
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or ""),
            goal_spec=goal_spec,
            task=task,
        )
        allow_readback = fast_path.task_kind not in {"bug_fix", "single_file_bugfix"}
        verification_results = [
            obs
            for obs in observations
            if _is_verification_observation(obs, allow_readback=allow_readback)
        ]
        contract = check_completion_contract(task, changed_files, verification_results)
        tool_calls = len(observations)
        verification_calls = contract.verification_total

        if result.status == "budget_exhausted":
            status = "blocked"
            exit_reason = "max_rounds"
            summary = "模型驱动循环撞上迭代保险丝（可 resume），本轮尚未收尾。"
        elif not contract.ok:
            status = "blocked"
            exit_reason = "tool_failed"
            summary = "任务完成契约未满足：" + "；".join(contract.violations)
        else:
            status = "done"
            exit_reason = "completed"
            summary = result.final_message or "模型驱动循环已完成并通过完成契约。"

        # TaskBoard enforces ready→in_progress→testing→reviewing→done; complete_task walks the
        # intermediate hops (a direct in_progress→done transition is rejected). Blocked is a valid
        # direct transition from in_progress, and carries the contract-violation note for the user.
        if status == "done":
            task_board.complete_task(task_id, notes=summary)
        else:
            task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, summary)

        # 证据契约对齐（脊梁作一等证据生产者）：把本任务的验证结果 + 任务执行证据落进与 FSM 同名的
        # sink,让下游消费者(review 的确定性快评/恢复判定、worker_result.validation_refs、
        # real_model_acceptance、runtime_validation_evidence)读到脊梁执行证据,而不是只看到空壳。
        # 无候选/experiments(直写模型),故不写 experiments.jsonl。
        contract_dict = contract.to_dict()
        validation_refs: list[str] = []
        if context.run_dir is not None:
            validation_refs = self.evidence_sink.record_validation_results(
                context,
                task,
                [{"tool_name": obs.tool_name, "args": {}} for obs in verification_results],
                verification_results,
            )
            # changed_files 来自成功观察的 artifact_refs(脊梁 _execute 不填 data.path,recorder 的
            # _changed_files 读不到)——用一个轻量 shim 把它喂进证据,让 replan 能据此推 expected_changed_files
            # 并让 artifacts.jsonl 记下产物。
            changed_shim = SimpleNamespace(ok=True, data={"changed_files": changed_files})
            self.evidence_sink.record_artifacts(context, task, [changed_shim])
            self.execution_evidence.record(
                context=context,
                task=task,
                action={"summary": summary, "tool_calls": [], "verification": []},
                tool_results=[changed_shim],
                verification_results=verification_results,
                status=status,
                summary=summary,
                actor="ModelDrivenTurn",
                contract_check=contract_dict,
            )
        evidence_path = context.run_dir / "tool_calls.jsonl" if context.run_dir else None
        # NB schema-double-trap: SUMMARY_STATUSES = {completed, blocked, waiting_user, stopped}
        # (NOT "succeeded"); EXIT_REASONS has no "budget_exhausted" — the fuse tripping IS the
        # max-rounds ceiling; a contract violation reports as tool_failed. Wrong values silently
        # downgrade to blocked / no_action.
        self._record_agent_loop_run_summary(
            context=context,
            task_id=task_id,
            status="completed" if status == "done" else "blocked",
            exit_reason=exit_reason,
            rounds_completed=result.iterations,
            max_rounds=max_iterations,
            summary=summary,
            recommended_command="review" if status == "done" else "status --debug",
            latest_decision=None,
            latest_execution=None,
            latest_observation=None,
            evidence_refs=self._refs(evidence_path),
        )
        return TaskExecutionSummary(
            task_id=task_id,
            status=status,
            summary=summary,
            tool_calls=tool_calls,
            verification_calls=verification_calls,
            evidence_path=evidence_path,
            validation_refs=validation_refs,
        )

    def _pause_model_driven_task(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        decision: dict,
        rounds_completed: int,
        max_rounds: int,
    ) -> TaskExecutionSummary:
        """脊梁命中人审边界时的收尾（ADR-0016：人审=显式边界）。复用 FSM 同一套 block/证据/进度落法：
        任务标 blocked + 留 pending DecisionPoint，run 层据 pending_decisions 把 run 报成 paused。"""
        task_id = task["task_id"]
        blocked = self.blocking_handler.block_for_policy_decision(
            context=context,
            task_board=task_board,
            task=task,
            action={
                "summary": "模型驱动循环命中执行策略人审边界，整批工具暂停待人批。",
                "tool_calls": [],
                "verification": [],
            },
            decision=decision,
        )
        self._record_agent_loop_run_summary(
            context=context,
            task_id=task_id,
            status="waiting_user",
            exit_reason="ask",
            rounds_completed=rounds_completed,
            max_rounds=max_rounds,
            summary=blocked.summary,
            recommended_command="decide --list",
            latest_decision=None,
            latest_execution=None,
            latest_observation=None,
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

    def _model_driven_prompts(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        runtime_context: dict,
        can_delegate: bool = False,
    ) -> tuple[str, str]:
        """Build the 立真身 turn envelope: rich task/goal/project/mounted context, but NO
        ``next_action`` enum / decision-table contract (that closed enum IS the FSM the
        model-driven loop escapes). The per-step JSON output contract is appended by
        ``run_model_driven_turn`` itself; here we only supply the grounding context."""
        system_prompt = (
            "You are CoderAgent in a local-first autonomous development runtime.\n"
            "Drive the task to completion yourself: at each step call the tools you need, read the "
            "observations you get back, then decide the next step. Verify your work with "
            "run_command / run_tests before you finish.\n"
            "- Make the smallest change that satisfies the task contract; stay within write_scope.\n"
            "- Tool or command failures come back to you as observations — adapt and retry; a "
            "failure does not block you and does not require anyone's permission to continue.\n"
            "- Only finish (done=true, empty tool_calls) once the expected artifact exists AND you "
            "have verified it.\n"
            "- narration is one short sentence in the user's language (Chinese) describing THIS step."
        ) + self._methodology_guidance(runtime_context, can_delegate=can_delegate)
        payload = {
            "task": task,
            "goal_spec": goal_spec,
            "task_contract": {
                "read_scope": task.get("read_scope", []),
                "write_scope": task.get("write_scope", []),
                "expected_artifacts": task.get("expected_artifacts", []),
                "validation_commands": task.get("validation_commands", []),
                "acceptance": task.get("acceptance", []),
            },
            "project": project_config,
            "runtime_context": context_prompt_view(runtime_context),
            "available_tools": available_tools,
            "allowed_tools": task.get("allowed_tools", []),
            "methodology_skills": self._methodology_skills(runtime_context),
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    def _methodology_skills(self, runtime_context: dict) -> list[dict]:
        """The task-allowed methodology procedures (skills) offered to the model, as
        {name, description} — progressive disclosure: the model sees only the one-line description
        and calls the skill to load its full procedure when it judges it relevant (ADR-0016 §1:
        methodology is OFFERED in the model's decision space, never a forced phase)."""
        surface = runtime_context.get("model_tool_surface")
        tools = surface.get("tools") if isinstance(surface, dict) else None
        if not isinstance(tools, list):
            return []
        skills: list[dict] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("kind") == "skill" and tool.get("task_allowed"):
                name = str(tool.get("name") or "")
                if name:
                    skills.append({"name": name, "description": str(tool.get("description") or "")})
        return skills

    def _methodology_guidance(self, runtime_context: dict, can_delegate: bool = False) -> str:
        """Trigger-conditional methodology guidance appended to the system prompt — SUGGESTIONS the
        model applies by judgment (not enforced phases; skip for simple tasks). Externalizing the
        plan via todo_write embodies the model's own organizational capability; the skill procedures
        cover diagnose/investigate/execute/verify/retrospect on demand. When ``can_delegate`` (the
        lead loop only), the model may also route a sub-task to a specialist via spawn_subagent."""
        skills = self._methodology_skills(runtime_context)
        lines = [
            "\n\nOptional methodology (use by judgment — suggestions, NOT required; skip simple tasks):",
            "- For a multi-step or unfamiliar task, externalize a plan with todo_write and update it "
            "as you go — this is your working memory, not a gate.",
        ]
        if skills:
            catalog = "\n".join(f"  - {item['name']}: {item['description']}" for item in skills)
            lines.append(
                "- These procedure skills are available; call one to load its steps when it fits the "
                "situation, then carry it out with your normal tools:\n" + catalog
            )
            lines.append(
                "  e.g. non-obvious failure -> skill__debug; unfamiliar code -> skill__investigate; "
                "before finishing -> skill__verify / skill__retrospect."
            )
        if can_delegate:
            lines.append(
                "- You may delegate a well-scoped sub-task to a specialist expert with a "
                'spawn_subagent tool call, e.g. {"tool_name": "spawn_subagent", "args": '
                '{"role": "coder", "task": "<what to do>", "read_scope": [...], "write_scope": [...]}}. '
                "Roles: " + ", ".join(expert_roles()) + ". The subagent runs independently with a "
                "fresh context and returns only a summary. Use it when a sub-task benefits from a "
                "focused expert; otherwise just do the work yourself."
            )
        return "\n".join(lines)

    def _record_model_driven_event(
        self,
        context: RuntimeContext,
        task: dict,
        event: TurnEvent,
    ) -> None:
        """Project 立真身 loop events onto the user progress stream: the model's narration/final
        message rides the main thread in its own voice (ADR-0021); tool observations land in the
        Inspector (evidence, not conversation)."""
        task_id = str(task.get("task_id") or "")
        if event.kind in {"narration", "final"} and event.text:
            self._record_progress(
                context,
                task,
                channel="model",
                event_type="message",
                phase="execute",
                status="running",
                title="模型叙述" if event.kind == "narration" else "模型收尾",
                summary=event.text,
                display_level="main",
                transcript_kind="assistant_message",
                data={
                    "task_id": task_id,
                    "iteration": event.iteration,
                    "model_driven_turn": True,
                },
            )
        elif event.kind == "tool_observation":
            for obs in event.observations:
                # status must be a valid user_progress enum (queued/running/waiting_user/completed/
                # failed/blocked) — NOT "warning". A failed observation does NOT fail the task here:
                # the loop feeds it back and the model decides the next step, so the task is still
                # "running". The ok/failure detail rides in the summary + data.ok.
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="message",
                    phase="execute",
                    status="running",
                    title=f"工具结果 · {obs.tool_name}"
                    + ("" if obs.ok else " (失败)"),
                    summary=obs.model_summary(),
                    display_level="inspector",
                    data={
                        "task_id": task_id,
                        "iteration": event.iteration,
                        "tool_name": obs.tool_name,
                        "ok": obs.ok,
                        "model_driven_turn": True,
                    },
                )
        elif event.kind == "fuse":
            # "running" (valid enum) — the terminal blocked status is set by the caller's
            # finalization; this is only an inspector breadcrumb, not the task's final status.
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title="迭代保险丝",
                summary="模型驱动循环达到迭代上限（预算保险丝），可 resume 继续。",
                display_level="inspector",
                data={"task_id": task_id, "iteration": event.iteration, "model_driven_turn": True},
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
            if self.mcp_discovered_tools:
                mcp_tools = mcp_model_tools(self.mcp_discovered_tools, task)
                task_model_surface["tools"].extend(mcp_tools)
                task_model_surface["task_allowed_model_tools"].extend(
                    str(tool["name"]) for tool in mcp_tools if tool.get("task_allowed")
                )
            if self.skill_discovered:
                skill_tools = skill_model_tools(self.skill_discovered, task)
                task_model_surface["tools"].extend(skill_tools)
                task_model_surface["task_allowed_model_tools"].extend(
                    str(tool["name"]) for tool in skill_tools if tool.get("task_allowed")
                )
            runtime_context["model_tool_surface"] = task_model_surface
            available_tools = model_tools_available_for_task(
                self.registry.names(),
                task,
                allow_shell=self._shell_allowed(context.policy),
            )
            # 立真身 (ADR-0016 §1): the model-driven single loop is the SOLE execution path
            # (RA7b slice3f deleted the FSM round loop + its helpers). The model drives itself
            # through the real ToolExecutionGateway (permissions / scope / sandbox / evidence
            # intact); max_iterations is a resumable budget fuse, not cognition. Reuses the
            # already-prepared task + RuntimeContext + full tool gateway. The except handlers
            # below still wrap this call (ToolPermissionDenied → runtime_request; generic → block).
            return self._run_model_driven_task(
                task=task,
                task_board=task_board,
                context=context,
                coder=coder,
                goal_spec=goal_spec,
                project_config=project_config,
                runtime_context=runtime_context,
                available_tools=available_tools,
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


_VERIFICATION_TOOL_NAMES = frozenset({"run_command", "run_tests", "run_pytest"})


def _is_verification_observation(observation: Any, *, allow_readback: bool = False) -> bool:
    """立真身把统一 tool_calls 里"跑命令"的观察当作验证证据。对齐 FSM 的 verification 分离：
    FSM 单列 ``action["verification"]``（清一色 run_command），脊梁没有这层分离，于是用工具名归类
    ——run_command 一类即验证。完成契约（task_contract）据此判定验证跑没跑 / 过没过（ADR-0016 边界）。

    ``allow_readback``：文档/报告类任务没有可执行命令,其"验证"就是把产物读回确认(对齐 review 的
    artifact_readback 计入 verification_call_count);代码类任务仍必须跑命令,read_file 不算数。"""
    name = str(getattr(observation, "tool_name", "") or "")
    if name in _VERIFICATION_TOOL_NAMES:
        return True
    return allow_readback and name == "read_file"


def _looks_like_path(value: str) -> str | bool:
    """A concrete relative FILE path (for the stop-guardrail) vs a prose placeholder or directory
    scope: no whitespace, and either a directory separator or a filename extension. A trailing-slash
    entry (e.g. ``src/``) is a directory SCOPE, not a deliverable file — the guardrail must not force
    the loop open waiting for it to "exist" (the model may legitimately write files anywhere in
    scope, or the concrete filename differs), so it is not treated as a path to check."""
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    if text.endswith("/") or text.endswith("\\"):
        return False
    return ("/" in text) or ("\\" in text) or ("." in Path(text).name)


def _methodology_turn_start_decision(record: dict) -> RuntimeHookDecision | None:
    """turn_start control hook: a one-time kickoff reminder of the available methodology (skills +
    todo self-organization), skewed to weaker models. Suggestion injected as context — NOT a phase.
    Strong models get less scaffolding (density by tier); reminder never repeats every turn."""
    if record.get("hook_name") != "turn_start":
        return None
    data = record.get("data") or {}
    try:
        iteration = int(data.get("iteration") or 0)
    except (TypeError, ValueError):
        iteration = 0
    if iteration != 1:  # kickoff only — do not bloat every turn
        return None
    if str(data.get("model_tier") or "") == "strong":  # strong models self-organize; low density
        return None
    hint = (
        "[methodology reminder] For a multi-step task, externalize a short plan with todo_write and "
        "verify your work (run_tests / run_command) before finishing."
    )
    skills = [str(name) for name in (data.get("methodology_skill_names") or []) if name]
    if skills:
        hint += " Optional procedure skills you may load when they fit: " + ", ".join(skills) + "."
    return RuntimeHookDecision(additional_context=hint)


def _methodology_stop_guardrail_decision(record: dict) -> RuntimeHookDecision | None:
    """pre_final(stop) control hook = the continuity guardrail. When the model tries to finish but a
    deterministic evidence boundary is unmet — an expected artifact does not exist on disk — hold
    the loop open and hand control BACK to the model with a factual nudge. It checks evidence and
    reopens the turn; it never decides HOW to fix (that stays the model's — ADR-0016). The loop's
    max_iterations fuse bounds it so it can never spin forever."""
    if record.get("hook_name") != "pre_final":
        return None
    data = record.get("data") or {}
    root = data.get("root")
    # Only enforce entries that look like a concrete relative file path — a task's expected_artifacts
    # / write_scope may hold prose placeholders (e.g. "implementation artifact"), which are not files
    # to check. Enforcing a non-path would wrongly hold the loop open forever.
    expected = [
        str(item)
        for item in (data.get("expected_artifacts") or [])
        if item and _looks_like_path(str(item))
    ]
    if not root or not expected:
        return None
    missing = [path for path in expected if not (Path(str(root)) / path).exists()]
    if not missing:
        return None
    return RuntimeHookDecision(
        additional_context=(
            "The task is not complete yet: expected artifact(s) not found: "
            + ", ".join(missing)
            + ". Produce and verify them with tool calls before finishing."
        ),
        continue_turn=True,
    )


@dataclass(frozen=True)
class _SubagentResult:
    """A summary-only result from a spawned expert sub-agent, shaped so
    ``observation_from_tool_result`` can consume it (ok / summary / status / error / data). Only the
    summary rides back to the lead model — the child's full context stays isolated (Claude Code
    Task-tool semantics)."""

    ok: bool
    summary: str
    status: str = "success"
    error: str | None = None
    data: dict = field(default_factory=dict)


class _SubagentAwareToolRunner:
    """Wraps the ToolExecutionGateway so the model-driven loop can call ``spawn_subagent``: that one
    call is routed to the spawn callback (which runs a child 立真身 loop), everything else delegates
    to the real gateway (permissions / sandbox / evidence intact). Keeps the frozen gateway
    untouched — the expert-cluster capability is added as a tool the model chooses, not a new FSM."""

    def __init__(self, gateway: Any, spawn: Callable[[dict], _SubagentResult]) -> None:
        self._gateway = gateway
        self._spawn = spawn

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: Any,
        stop_on_failure: bool = True,
        stop_verification_on_fatal: bool = False,
    ) -> list[Any]:
        results: list[Any] = []
        for call in calls:
            if str(call.get("tool_name") or "") == "spawn_subagent":
                results.append(self._spawn(call.get("args") or {}))
            else:
                results.extend(
                    self._gateway.run_tool_calls(
                        [call],
                        task,
                        context,
                        stop_on_failure=stop_on_failure,
                        stop_verification_on_fatal=stop_verification_on_fatal,
                    )
                )
        return results
