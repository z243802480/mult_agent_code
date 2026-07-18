from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from asteria_runtime.core.context_budget import slim_workspace_files
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.context_prompt_view import context_prompt_view
from asteria_runtime.core.expert_registry import expert_roles, resolve_expert
from asteria_runtime.core.worker_executor import (
    SubagentOutcome,
    SubagentRequest,
    resolve_worker_executor,
)
from asteria_runtime.core.model_driven_turn import (
    TurnControl,
    TurnEvent,
    run_model_driven_turn,
)
from asteria_runtime.core.task_progress_digest import (
    load_task_progress,
    record_task_progress,
    render_prior_progress,
)
from asteria_runtime.core.run_control import (
    clear_pause,
    pause_reason,
    pause_requested,
    take_steer,
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
from asteria_runtime.core.permission_policy import autonomy_rings_default_on
from asteria_runtime.core.run_config import effective_policy_for_run
from asteria_runtime.storage import audit_chain
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
from asteria_runtime.core.task_contract import (
    check_completion_contract,
    looks_like_file_path,
    path_in_write_scope,
)
from asteria_runtime.core.workspace_snapshot import changed_paths, snapshot_workspace
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder, WorkerExecutionSlot
from asteria_runtime.core.worker_runner import WorkerRunner
from asteria_runtime.core.workspace_writer_lock import workspace_writer_lock
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
        # S88: `debug` and bare `execute` enter here without passing RunCommand, so the
        # cross-process writer lock must sit on this door too. Re-entrant when a RunCommand
        # already holds it for this root.
        with workspace_writer_lock(self.root, command="execute"):
            return self._run_unlocked()

    def _run_unlocked(self) -> ExecuteResult:
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
        # Audit tamper-evidence (S77 P1): set the process-wide chain toggle from policy before any
        # audit JSONL is written this run. Off by default → JsonlStore behaves byte-identically.
        audit_chain.configure_from_policy(policy)
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
        # 用户暂停的任务回到 ready —— 但必须等这一轮任务选择**跑完之后**再放回去。
        # 在暂停处理里当场重置会让同一轮的 coordinator 立刻又把它挑起来(此时信号已被消费),
        # 于是暂停自己把自己作废掉:任务照跑不误。(真机跑出来的 bug,不是假想的。)
        # 也不能标 blocked——blocked 会喂进 replan 环,让引擎去重新分解一个用户只是想暂停的目标。
        for item in executed:
            if item.status != "paused":
                continue
            if task_board.get_task(item.task_id).get("status") == "in_progress":
                task_board.update_status(item.task_id, "ready")

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

    def _model_turn_iteration_fuse(self, policy: dict) -> int:
        """Per-task turn fuse for the model-driven loop (ADR-0016): a runaway backstop, NOT a
        cognitive round ceiling.

        The former derivation ``max_rounds_per_task(≤8) + 4`` (default 6) was inherited from the
        retired FSM's per-task *round* concept and is far too tight for a read-heavy edit: the model
        reads several files to understand the code, and the fuse trips before it can write. When the
        fuse trips the task is marked ``budget_exhausted`` → replanned, and the replan re-reads
        everything from scratch (dogfood residual②, run-20260718 — the model spent its whole budget
        navigating instead of editing). The fuse is a boundary, not cognition, so the real governors
        stay the goal-level cost budget (``max_model_calls``/``max_tool_calls_per_goal``) and the
        ``loop_quality_guard`` repeated-tool window; this only stops a *single* task turn from
        spinning forever. Default headroom is generous (16) so read-then-edit finishes in one turn;
        override with ``agent_loop.max_turn_iterations`` (e.g. tests force a quick fuse with a small
        value, prod could widen it further)."""
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        override = agent_loop.get("max_turn_iterations")
        if override is not None:
            try:
                return max(1, int(override))
            except (TypeError, ValueError):
                pass
        return max(self._agent_loop_max_rounds(policy) + 4, 16)

    def _auto_repair_enabled(self, policy: dict) -> bool:
        # Default bound to the permission mode (set-and-forget): auto/reviewed_auto → on so a
        # failed task self-repairs within budget instead of stopping to ask; ask_everything → off.
        # An explicit agent_loop.auto_repair flag still overrides. (User-authorized flip 2026-07-13.)
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(
            agent_loop.get("auto_repair", autonomy_rings_default_on(policy.get("permission_mode")))
        )

    def _mid_run_steer_enabled(self, policy: dict) -> bool:
        # ADR-0029 ①: whether a user instruction dropped into the run dir (steer.request) is injected
        # at the next turn boundary. Default ON (2026-07-16 DecisionPoint, changelog 1.2.76). Behaviour
        # is still byte-identical to today whenever no steer.request exists — the signal is only read at
        # a turn boundary and only when the file is present, so a run nobody steers is unchanged. This is
        # NOT an autonomy ring (it delivers the user's OWN words, no self-driving), so it does not bind to
        # the permission mode; set agent_loop.mid_run_steer=false in policy to restore queue-for-after.
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("mid_run_steer", True))

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
        # Default bound to the permission mode (set-and-forget): auto/reviewed_auto → on,
        # ask_everything → off; explicit agent_loop.auto_replan overrides. (Flip 2026-07-13.)
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(
            agent_loop.get("auto_replan", autonomy_rings_default_on(policy.get("permission_mode")))
        )

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
            "duplicate_content_hash_count": len(
                report.get("context_duplicate_content_hashes") or []
            ),
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

    def _concurrent_subagents_enabled(self, policy: dict) -> bool:
        """Whether a batch of ≥2 spawn_subagent calls to read-only experts runs concurrently
        (ADR-0023 B1-a). Default bound to the permission mode (set-and-forget): auto/reviewed_auto →
        on so the model's concurrent expert fan-out is the default; ask_everything → off (byte-
        identical serial fan-out for explicit step-by-step supervision). An explicit
        agent_loop.concurrent_subagents flag still overrides. (User-authorized global-default flip
        2026-07-14; read-only fan-out has no writes so no conflict risk.)"""
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(
            agent_loop.get(
                "concurrent_subagents", autonomy_rings_default_on(policy.get("permission_mode"))
            )
        )

    def _max_parallel_workers(self, policy: dict) -> int:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        try:
            value = int(agent_loop.get("max_parallel_workers_per_run") or 16)
        except (TypeError, ValueError):
            value = 16
        return max(1, value)

    def _isolated_parallel_writes_enabled(self, policy: dict) -> bool:
        """Whether a batch of ≥2 spawn_subagent calls that includes WRITING experts fans out
        concurrently, each in its own candidate workspace, reconciled through the merge gate before
        promotion (ADR-0023 B1-b). Default bound to the permission mode (set-and-forget): auto/
        reviewed_auto → on so concurrent expert writes are the default capability; ask_everything →
        off (writing batches stay serial on the shared workspace for explicit step-by-step review).
        Safety is unconditional regardless of the default: each writer runs in its OWN candidate
        workspace and the batch reconciles through ONE cross-task merge gate — all disjoint writers
        promote or none do (never a partial merge of cross-conflicting writes), and candidate
        creation falls back to a plain copy when git worktrees are unavailable. An explicit
        agent_loop.isolated_parallel_write_production_path flag still overrides. (User-authorized
        global-default flip 2026-07-14, resolving the prior autonomy/safety DecisionPoint; the
        merge-gate-protected B1-b path was real-stack validated in §16 v1.2.25/1.2.26/1.2.29.)"""
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(
            agent_loop.get(
                "isolated_parallel_write_production_path",
                autonomy_rings_default_on(policy.get("permission_mode")),
            )
        )

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
        candidate-promotion attempt runner.

        Not gated by anything: this is the ONLY execution path. It was behind
        ``agent_loop.model_driven_turn`` until RA7a flipped that default on, and RA7b retired the
        flag along with the FSM it selected between (no reader in src/, no key in the policy schema).
        """
        task_id = task["task_id"]
        # max_iterations is a fuse (budget boundary), NOT the FSM's cognitive round ceiling. Read-heavy
        # edits need real headroom (read many files → then write) or the fuse trips mid-navigation and
        # the replan re-reads from scratch; the hard budget/hard-stop + loop guard still govern cost.
        max_iterations = self._model_turn_iteration_fuse(context.policy)
        # residual② persistence half: if a previous attempt at this task ran (fuse trip / pause /
        # resume), carry forward a compact ledger of what it already did so this attempt continues
        # instead of re-reading from scratch. Empty on the first attempt → byte-identical to before.
        prior_progress = render_prior_progress(
            load_task_progress(context.run_dir, str(task.get("task_id") or ""))
        )
        # Prompt-eval report rec #2: the doer never saw the project's own conventions. AGENTS.md is
        # read into the persisted prompt_envelope but that text is not fed to the model
        # (context_prompt_view strips it). Carry it into the doer prompt directly, like Claude Code
        # puts CLAUDE.md in the system prompt — read once here, reused for the lead and every expert.
        project_guidance = self._project_guidance(context.root)
        system_prompt, user_prompt = self._model_driven_prompts(
            task,
            goal_spec,
            project_config,
            available_tools,
            runtime_context,
            can_delegate=True,
            prior_progress=prior_progress,
            project_guidance=project_guidance,
        )
        model_tier = str(runtime_context.get("execution_model_tier") or "strong")
        max_subagent_depth = self._max_subagent_depth(context.policy)
        subagent_counter = {"n": 0}
        # Guards the child-index counter so concurrent fan-out (ADR-0023) cannot mint a colliding
        # child_task_id. Evidence appends are already serialized by JsonlStore / UserProgressLogger.
        subagent_counter_lock = threading.Lock()
        # Batch identity (B4): concurrency was never IN the evidence — the smoke had to infer it from
        # card ordering. A batch stamps every card it fans out, so the UI reads "2 experts in
        # parallel" off a field instead of guessing. Serial spawns carry no batch (cards unchanged).
        batch_counter = {"n": 0}
        concurrent_subagents = self._concurrent_subagents_enabled(context.policy)
        max_parallel_workers = self._max_parallel_workers(context.policy)
        isolated_parallel_writes = self._isolated_parallel_writes_enabled(context.policy)

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
            # A hook that HELD THE LOOP OPEN changed what the user sees: the model tried to finish and
            # the run kept going. Without a card that reads as "还差 X 没产出,让它继续做" the extra
            # rounds look like the agent spinning for no reason. Only continue_turn earns a card —
            # the turn_start reminder injection is scaffolding and stays in the Inspector (the main
            # thread does not narrate how the loop prompts itself).
            if decision.continue_turn:
                missing = [str(item) for item in (decision.facts.get("missing_artifacts") or [])]
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="message",
                    phase="execute",
                    status="running",
                    title="还差产出,继续做",
                    summary=(
                        "模型想收尾,但这些交付物还没出现:"
                        + "、".join(missing)
                        + "。已让它继续完成并验证。"
                        if missing
                        else "模型想收尾,但完成条件还没满足。已让它继续。"
                    ),
                    display_level="main",
                    transcript_kind="verification",
                    data={
                        "task_id": str(task.get("task_id") or ""),
                        "hook_name": event_name,
                        "held_open": True,
                        "missing_artifacts": missing,
                        "iteration": payload.get("iteration"),
                        "model_driven_turn": True,
                    },
                )
            return TurnControl(
                additional_context=decision.additional_context,
                continue_turn=decision.continue_turn,
            )

        def _prepare_child(args: dict) -> tuple[Any, str, dict, dict] | _SubagentResult:
            # Build one expert child's task scaffolding (depth-guarded, uniquely numbered). Shared by
            # the serial path and the concurrent isolated-write batch so both mint identical children.
            # The depth guard returns BEFORE the counter increments, so a refused child never burns a
            # child_task_id (a batch that falls back to serial re-prepares without double-counting).
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
            with subagent_counter_lock:
                subagent_counter["n"] += 1
                child_index = subagent_counter["n"]
            child_task_id = f"{task_id}-sub-{child_index:02d}"
            child_allowed = self._subagent_allowed_tools(task, expert)
            child_task = {
                "task_id": child_task_id,
                "title": f"{expert.role} subagent",
                "description": str(args.get("task") or ""),
                "allowed_tools": child_allowed,
                "read_scope": [
                    str(item)
                    for item in (args.get("read_scope") or task.get("read_scope") or [])
                    if item
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
            return expert, child_task_id, child_task, child_runtime_context

        def _run_child(
            expert: Any,
            child_task_id: str,
            child_task: dict,
            child_runtime_context: dict,
            args: dict,
            *,
            child_context: RuntimeContext,
            batch: dict | None = None,
        ) -> SubagentOutcome:
            # Run one expert's bounded 立真身 loop and light up the dispatch + result cards on the
            # lead's main thread (ADR-0022 ③). ``child_context`` is the lead's SHARED workspace for
            # serial fanout, or an ISOLATED candidate context for concurrent writes (B1-b) — the
            # child's writes land in whichever root that context carries, since the gateway resolves
            # every path against ``context.root``. Pluggable backend: LocalExecutor (in-process,
            # default) / CloudSessionExecutor (North Star stub). The dispatch card shows immediately
            # (a long expert run is otherwise silent); the child's own narration/tools stay in the
            # Inspector (subagent_role); only the returned summary rides back up.
            child_system, child_user = self._model_driven_prompts(
                child_task,
                goal_spec,
                project_config,
                child_task["allowed_tools"],
                child_runtime_context,
                project_guidance=project_guidance,
            )
            child_system = f"{child_system}\n\n[Expert role: {expert.role}] {expert.persona}"
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title=f"委派 {expert.role} 专家",
                summary=f"委派 {expert.role} 专家：{str(args.get('task') or '').strip()[:200]}",
                display_level="main",
                transcript_kind="subagent_summary",
                data={
                    "task_id": task_id,
                    "subagent_role": expert.role,
                    "child_task_id": child_task_id,
                    "subagent_phase": "dispatch",
                    "model_driven_turn": True,
                    **(batch or {}),
                },
            )
            executor = resolve_worker_executor(
                self._subagent_backend_kind(context.policy), validator=self.validator
            )
            outcome = executor.run_subagent(
                SubagentRequest(
                    role=expert.role,
                    task=child_task,
                    system_prompt=child_system,
                    user_prompt=child_user,
                    available_tools=child_task["allowed_tools"],
                    model_tier=expert.model_tier,
                    max_iterations=max_iterations,
                    # Bill the expert's calls to the SAME worker profile as the task that delegated
                    # them — a delegated call is still that task's cost, so the worker tree stays
                    # whole. `subagent_role` + the child's own task_id keep it attributable per
                    # expert, so "which expert cost what" is answerable without double counting (B7).
                    call_attribution={
                        "runtime_profile_id": runtime_context.get("runtime_profile_id"),
                        "worker_invocation_id": runtime_context.get("current_worker_invocation_id"),
                        "run_id": context.run_id,
                        "subagent_role": expert.role,
                    },
                ),
                model_client=coder.model_client,
                tool_runner=self.tool_gateway,
                context=child_context,
                on_event=lambda event: self._record_model_driven_event(
                    context, child_task, event, subagent_role=expert.role
                ),
            )
            # Returned-summary card on the main thread — lights up the wired "子 agent" narrative
            # kind (narrative.ts subagent_summary → subagent) with the expert's role + result.
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="completed" if outcome.ok else "running",
                title="子 agent 完成" if outcome.ok else "子 agent 未完成",
                summary=f"[{expert.role}] {outcome.summary}",
                display_level="main",
                transcript_kind="subagent_summary",
                data={
                    "task_id": task_id,
                    "subagent_role": expert.role,
                    "child_task_id": child_task_id,
                    "subagent_phase": "result",
                    "child_status": outcome.status,
                    "iterations": outcome.iterations,
                    "ok": outcome.ok,
                    "model_driven_turn": True,
                    # What the expert actually DID (B4). The executor already returned these; they
                    # went only to the lead model, so the UI could not say which expert touched
                    # which file, on which tier, through which backend.
                    "changed_files": list(outcome.data.get("changed_files") or []),
                    "backend": str(outcome.data.get("backend") or ""),
                    "model_tier": str(getattr(expert, "model_tier", "") or ""),
                    "read_only": bool(getattr(expert, "read_only", False)),
                    # What this expert cost (B7) — attributable now that each model call carries the
                    # task_id that spent it.
                    "cost": self._model_cost_for_task(context, child_task_id),
                    **(batch or {}),
                },
            )
            return outcome

        def _result_from_outcome(
            expert: Any, child_task_id: str, outcome: SubagentOutcome
        ) -> _SubagentResult:
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

        def _spawn_subagent(args: dict, *, batch: dict | None = None) -> _SubagentResult:
            # Expert-cluster delegation (ADR-0022): the lead model routes a scoped sub-task to a
            # specialist that runs its OWN bounded 立真身 loop on the SHARED workspace and returns ONLY
            # a summary. Serial default; concurrency + candidate isolation is the batch path below.
            prepared = _prepare_child(args)
            if isinstance(prepared, _SubagentResult):
                return prepared
            expert, child_task_id, child_task, child_runtime_context = prepared
            outcome = _run_child(
                expert,
                child_task_id,
                child_task,
                child_runtime_context,
                args,
                child_context=context,
                batch=batch,
            )
            return _result_from_outcome(expert, child_task_id, outcome)

        def _new_batch_id() -> str:
            with subagent_counter_lock:
                batch_counter["n"] += 1
                index = batch_counter["n"]
            return f"{task_id}-batch-{index:02d}"

        def _batch_card(batch_id: str, size: int, index: int, mode: str) -> dict:
            # Stamped onto every card a batch fans out. ``concurrent`` is the fact the evidence was
            # missing: before B4 the only way to know was to guess from card ordering.
            return {
                "batch_id": batch_id,
                "batch_size": size,
                "batch_index": index,
                "batch_mode": mode,
                "concurrent": True,
            }

        def _spawn_isolated_writes(
            prepared_list: list[tuple[Any, str, dict, dict]],
            spawn_args_list: list[dict],
        ) -> list[_SubagentResult]:
            # ADR-0023 B1-b: run a batch of WRITING experts CONCURRENTLY, each in its OWN candidate
            # workspace, then reconcile through the merge gate and promote atomically. Candidate
            # creation runs SERIALLY on this thread first — `_candidate_id()` is timestamp-based and
            # `git worktree add` mutates the shared repo, neither is thread-safe; only the expensive
            # model-driven child RUNS fan out. Read-only children in a mixed batch keep the shared
            # context (they write nothing). On join, every writer's candidate is judged by ONE
            # cross-task merge gate: all disjoint writers promote into the shared workspace, or none
            # do (never a partial merge of cross-conflicting writes).
            candidates: dict[str, Any] = {}
            for expert, child_task_id, child_task, _child_rc in prepared_list:
                if getattr(expert, "read_only", False):
                    continue
                candidates[child_task_id] = self.candidate_gateway.create_workspace(
                    context, child_task
                )

            outcomes: list[SubagentOutcome | None] = [None] * len(prepared_list)
            batch_size = len(prepared_list)
            batch_id = _new_batch_id()

            def _run_indexed(index: int) -> SubagentOutcome:
                expert, child_task_id, child_task, child_rc = prepared_list[index]
                candidate = candidates.get(child_task_id)
                child_ctx = (
                    self.candidate_gateway.candidate_context(context, candidate)
                    if candidate is not None
                    else context
                )
                return _run_child(
                    expert,
                    child_task_id,
                    child_task,
                    child_rc,
                    spawn_args_list[index],
                    child_context=child_ctx,
                    batch=_batch_card(batch_id, batch_size, index, "isolated_writes"),
                )

            workers = min(len(prepared_list), max_parallel_workers)
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="expert-write") as pool:
                futures = {
                    pool.submit(_run_indexed, index): index for index in range(len(prepared_list))
                }
                for future in as_completed(futures):
                    outcomes[futures[future]] = future.result()

            # Reconcile writers through ONE merge gate (serial, main thread). Only successful writers
            # with actual changes are candidates for promotion.
            batch_items: list[dict] = []
            writer_indices: set[int] = set()
            for index, (expert, child_task_id, child_task, _rc) in enumerate(prepared_list):
                candidate = candidates.get(child_task_id)
                outcome = outcomes[index]
                if candidate is None or outcome is None or not outcome.ok:
                    continue
                changed = list(outcome.data.get("changed_files") or [])
                if not changed:
                    continue
                writer_indices.add(index)
                batch_items.append(
                    {"candidate": candidate, "task": child_task, "changed_files": changed}
                )

            promoted_by_task: dict[str, list[str]] = {}
            merge_ok = True
            merge_summary = ""
            if batch_items:
                dry_run, promoted_by_task = self.candidate_gateway.preview_and_promote_batch(
                    context, batch_items
                )
                merge_ok = bool(dry_run.get("ok"))
                merge_summary = str(dry_run.get("summary") or "")
                promoted_count = sum(len(files) for files in promoted_by_task.values())
                self._record_progress(
                    context,
                    task,
                    channel="progress",
                    event_type="message",
                    phase="execute",
                    status="completed" if merge_ok else "blocked",
                    title="并发写合并" if merge_ok else "并发写合并阻止",
                    summary=(
                        f"并发隔离写合并门通过，晋升 {promoted_count} 个文件到工作区。"
                        if merge_ok
                        else f"并发隔离写被合并门阻止：{merge_summary}"
                    ),
                    display_level="main",
                    transcript_kind="subagent_summary",
                    data={
                        "task_id": task_id,
                        "subagent_phase": "merge_gate",
                        "ok": merge_ok,
                        "promoted_files": promoted_count,
                        "model_driven_turn": True,
                        # Binds this merge back to the batch of experts it reconciled (B4).
                        "batch_id": batch_id,
                        "batch_size": batch_size,
                    },
                )

            results: list[_SubagentResult] = []
            for index, (expert, child_task_id, child_task, _rc) in enumerate(prepared_list):
                outcome = outcomes[index]
                if outcome is None:
                    results.append(
                        _SubagentResult(
                            ok=False,
                            status="failure",
                            error="subagent_no_result",
                            summary=f"[{expert.role}] subagent produced no result.",
                        )
                    )
                    continue
                if index in writer_indices and not merge_ok:
                    # Merge gate blocked → nothing promoted; the writer's isolated changes stay in its
                    # candidate (shared workspace untouched). Surface as a failure so the LEAD model
                    # sees it and decides the next step (ADR-0016: cognition stays with the model).
                    results.append(
                        _SubagentResult(
                            ok=False,
                            status="failure",
                            error="merge_gate_blocked",
                            summary=f"[{expert.role}] 并发写被合并门阻止：{merge_summary}",
                            data={
                                "role": expert.role,
                                "child_task_id": child_task_id,
                                "iterations": outcome.iterations,
                                "child_status": outcome.status,
                                "changed_files": [],
                            },
                        )
                    )
                    continue
                result = _result_from_outcome(expert, child_task_id, outcome)
                if index in writer_indices:
                    # Credit the LEAD only with what actually landed in the shared workspace.
                    result.data["changed_files"] = list(promoted_by_task.get(child_task_id) or [])
                results.append(result)
            return results

        def _spawn_batch(spawn_args_list: list[dict]) -> list[_SubagentResult]:
            # Model-driven concurrency (ADR-0023): when the lead puts ≥2 spawn_subagent calls in ONE
            # tool batch and the flag is on, fan them out. All read-only → shared-context concurrency
            # (B1-a: no writes → no conflict → no isolation; evidence appends are lock-serialized).
            # Any writer + isolated-write flag on → per-child candidate isolation + merge gate (B1-b).
            # Otherwise serial: a single call, the flag off, or writers present with the isolated-write
            # path still off (byte-identical to today).
            if len(spawn_args_list) < 2 or not concurrent_subagents:
                return [_spawn_subagent(args) for args in spawn_args_list]
            experts = [resolve_expert(args.get("role")) for args in spawn_args_list]
            if all(getattr(expert, "read_only", False) for expert in experts):
                results: list[_SubagentResult | None] = [None] * len(spawn_args_list)
                workers = min(len(spawn_args_list), max_parallel_workers)
                size = len(spawn_args_list)
                fanout_id = _new_batch_id()
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="expert") as pool:
                    futures = {
                        pool.submit(
                            _spawn_subagent,
                            args,
                            batch=_batch_card(fanout_id, size, index, "readonly_fanout"),
                        ): index
                        for index, args in enumerate(spawn_args_list)
                    }
                    for future in as_completed(futures):
                        results[futures[future]] = future.result()
                return [result for result in results if result is not None]
            if not isolated_parallel_writes:
                return [_spawn_subagent(args) for args in spawn_args_list]
            # Isolated concurrent writes (B1-b). Prepare every child first; if any hits the depth cap
            # (uniform across a batch) fall back to serial so the guard result surfaces unchanged.
            prepared_list: list[tuple[Any, str, dict, dict]] = []
            for args in spawn_args_list:
                prepared = _prepare_child(args)
                if isinstance(prepared, _SubagentResult):
                    return [_spawn_subagent(inner) for inner in spawn_args_list]
                prepared_list.append(prepared)
            return _spawn_isolated_writes(prepared_list, spawn_args_list)

        tool_runner = _SubagentAwareToolRunner(
            self.tool_gateway, _spawn_subagent, spawn_batch=_spawn_batch
        )

        def _approval_gate(calls: list[dict]) -> dict | None:
            # 人审边界（ADR-0016）：把模型这一步要跑的整批工具当作一个待审动作，交给与 FSM 同一套
            # 执行策略去判定——命中 shell denylist 且尚无 approve_once 决策就生成一个 execution_policy_
            # approval DecisionPoint（已在案则返回 None）。策略/决策归 harness，脊梁循环只在执行边界拦。
            return self.tool_permission_policy.create_policy_decision_if_needed(
                action={"tool_calls": list(calls), "verification": []},
                task=task,
                context=context,
            )

        # Disk truth for the completion contract (dogfood run-20260718-0001): a doer denied by
        # tool-layer scope can still write through run_command; the tool ledger then reports zero
        # changed files while the work sits finished on disk. Stat-level snapshot before/after the
        # turn lets the contract count in-scope disk changes and disclose out-of-scope ones.
        pre_turn_snapshot = snapshot_workspace(context.root)

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
            # 用户暂停信号由外部进程(Studio / `asteria pause`)写进 run 目录——运行中的 loop 只能靠
            # 文件看见它。回调注入,循环本身不碰文件系统。
            pause_requested=(
                (lambda: pause_requested(context.root / ".asteria" / "runs" / str(context.run_id)))
                if context.run_id
                else None
            ),
            # 中途 steer（ADR-0029 ①）：与 pause 同一投递语义——外部进程（Studio / CLI）把用户指令写进
            # run 目录，运行中的 loop 只在回合边界读并清、经 messages.append(role="user") 注入。回调注入，
            # 循环不碰文件系统。flag 默认关时不注入 → 逐字节同今日（steer.request 不被读，前端排队照旧）。
            take_steer=(
                (lambda: take_steer(context.root / ".asteria" / "runs" / str(context.run_id)))
                if (context.run_id and self._mid_run_steer_enabled(context.policy))
                else None
            ),
            # Cost attribution (B7): the worker tree counts a task's model calls by matching
            # runtime_profile_id, and the spine never stamped one — so a run that made 5 calls
            # reported 0. runtime_context carries the mounted profile; pass it through.
            call_attribution={
                "runtime_profile_id": runtime_context.get("runtime_profile_id"),
                "worker_invocation_id": runtime_context.get("current_worker_invocation_id"),
                "run_id": context.run_id,
                "subagent_role": runtime_context.get("subagent_role"),
            },
        )

        # residual② persistence half: merge this attempt's tool actions into the task's on-disk
        # progress digest (before ANY status branch below returns), so a replan/pause-resume of THIS
        # task carries forward what was already read/run instead of re-navigating from scratch. The
        # ledger stores one-line action summaries only — never the file content that blew the budget.
        record_task_progress(context.run_dir, str(task.get("task_id") or ""), result.observations)

        # 人审边界命中（ADR-0016：人审=显式边界）：脊梁在跑到需人批的工具批前整批停手，本轮无残留
        # 写入。复用 FSM 同一套 block/证据/进度落法（单一真源），把任务标 blocked 并留下 pending
        # DecisionPoint —— run 层据 pending_decisions 把整个 run 报成 paused。人批后 resume 重跑本任务，
        # gate 认到 approval 便放行整批。
        # 用户暂停（无待批决策）：脊梁在回合边界整批停手。任务**不标 blocked**——它没有失败,只是被
        # 用户按了暂停；resume 会重跑这个任务,已完成的工件都还在。也不走完成契约判定,否则会把"做了
        # 一半"当成"没做完契约"判 blocked,把一次正常的暂停污染成一次失败。
        if result.status == "paused":
            # Real work done before the pause — never report 0. The two pause summaries used to
            # hardcode tool_calls=0/verification_calls=0, which zeroed the worker tree's activity/cost
            # counters and review's collaboration summary for a task that had already run several tools.
            # A pause is not a completion judgment, so count activity with the SAME detectors as the
            # completion path, without running check_completion_contract.
            paused_tool_calls, paused_verification_calls = self._paused_activity_counts(
                result, goal_spec, task
            )
            if result.pending_decision is None:
                return self._user_paused_model_driven_task(
                    task=task,
                    task_board=task_board,
                    context=context,
                    rounds_completed=result.iterations,
                    max_rounds=max_iterations,
                    tool_calls=paused_tool_calls,
                    verification_calls=paused_verification_calls,
                )
            return self._pause_model_driven_task(
                task=task,
                task_board=task_board,
                context=context,
                decision=result.pending_decision,
                rounds_completed=result.iterations,
                max_rounds=max_iterations,
                tool_calls=paused_tool_calls,
                verification_calls=paused_verification_calls,
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
        # Union the tool ledger with what actually changed on disk. In-scope disk changes count as
        # progress no matter which path produced them (write_file or a shell command); out-of-scope
        # ones are disclosed on the contract instead of staying invisible. An empty/absent
        # write_scope means the tool layer imposed no path restriction, so nothing is "unscoped".
        disk_changed = changed_paths(pre_turn_snapshot, snapshot_workspace(context.root))
        write_scope = [str(item) for item in (task.get("write_scope") or []) if item]
        if write_scope:
            scope_kind = str(task.get("task_kind") or "") or None
            in_scope_disk = [
                path
                for path in disk_changed
                if path_in_write_scope(path, write_scope, kind=scope_kind)
            ]
            unscoped_disk = [path for path in disk_changed if path not in in_scope_disk]
        else:
            in_scope_disk = disk_changed
            unscoped_disk = []
        changed_files = sorted({*changed_files, *in_scope_disk})
        # 验证证据口径与 review 的确定性快评保持一致(单一真源语义):仅 bug_fix/single_file_bugfix
        # 要求可执行命令验证,其余(含 doc_update)读回产物即算验证。用同一 classify_fast_path 判定,
        # 避免执行门与评审门对"何为验证"各执一词。
        fast_path = classify_fast_path(
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or ""),
            goal_spec=goal_spec,
            task=task,
        )
        allow_readback = fast_path.task_kind not in {"bug_fix", "single_file_bugfix"}
        # Judge verification on each command's LATEST outcome (red→green on the same command passes),
        # not the cumulative pass/fail of every call — else the repair loop's mandatory initial
        # failing test dooms a genuinely fixed task (ring_recovery benchmark, 2026-07-14).
        verification_results = _latest_verification_per_command(
            [
                obs
                for obs in observations
                if _is_verification_observation(obs, allow_readback=allow_readback)
            ]
        )
        # NB: we deliberately do NOT pass allow_verified_noop=True here. It was tempting for repair
        # tasks (a real fix whose changed-files detection false-negatived), but real-stack validation
        # (ring_val_f) showed it opens a false-completion hole: a task can "close" by running ANY
        # passing command (not the acceptance test) with zero changed files. Blocking a no-op is the
        # safe, mainstream-aligned choice — completion requires a real changed artifact AND the real
        # verification passing. The changed-files detection gap is fixed at the source, not papered
        # over by trusting an arbitrary passing verification.
        contract = check_completion_contract(
            task, changed_files, verification_results, unscoped_changed_files=unscoped_disk
        )
        tool_calls = len(observations)
        verification_calls = contract.verification_total

        # Verified-complete DOMINATES the round fuse. Mainstream harnesses treat the model finishing
        # its work as "done"; a flat iteration counter is only a runaway backstop, never a reason to
        # discard genuinely-completed, contract-satisfying work. Checking `budget_exhausted` first
        # wrongly blocked a task that satisfied its completion contract on the very turn it hit the
        # fuse — which then fed the goal-replan ring an already-finished task and made it spin
        # (real-stack finding, ring_val_b). So: contract satisfied → done, even if the fuse also tripped.
        if contract.ok:
            status = "done"
            exit_reason = "completed"
            summary = result.final_message or "模型驱动循环已完成并通过完成契约。"
        elif result.status == "budget_exhausted":
            status = "blocked"
            exit_reason = "max_rounds"
            summary = "模型驱动循环撞上迭代保险丝（可 resume），本轮尚未收尾。"
            # Don't let "ran out of rounds" hide WHY it isn't done. If the completion contract also has
            # a hard violation (e.g. verification still failing), name it — otherwise the user resumes
            # believing a few more rounds will finish work that is actually blocked on a failing check.
            # exit_reason stays "max_rounds" so the soft-fuse still offers resume; only the note gets
            # honest about the real cause.
            if contract.violations:
                summary += "（未满足的完成契约：" + "；".join(contract.violations) + "）"
        else:
            status = "blocked"
            exit_reason = "tool_failed"
            summary = "任务完成契约未满足：" + "；".join(contract.violations)

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

    def _paused_activity_counts(self, result: Any, goal_spec: dict, task: dict) -> tuple[int, int]:
        """How much work actually happened before the pause. Counted with the SAME detectors as the
        completion path (classify_fast_path → allow_readback → _latest_verification_per_command), so a
        paused task reports real (tool_calls, verification_calls) instead of a hardcoded 0. A pause is
        not a completion judgment, so we count activity without running check_completion_contract."""
        observations = result.observations
        fast_path = classify_fast_path(
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or ""),
            goal_spec=goal_spec,
            task=task,
        )
        allow_readback = fast_path.task_kind not in {"bug_fix", "single_file_bugfix"}
        verification_results = _latest_verification_per_command(
            [
                obs
                for obs in observations
                if _is_verification_observation(obs, allow_readback=allow_readback)
            ]
        )
        return len(observations), len(verification_results)

    def _pause_model_driven_task(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        decision: dict,
        rounds_completed: int,
        max_rounds: int,
        tool_calls: int = 0,
        verification_calls: int = 0,
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
        return self._blocked_task_summary(
            blocked, tool_calls=tool_calls, verification_calls=verification_calls
        )

    def _model_driven_prompts(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        runtime_context: dict,
        can_delegate: bool = False,
        prior_progress: str | None = None,
        project_guidance: str | None = None,
    ) -> tuple[str, str]:
        """Build the 立真身 turn envelope: rich task/goal/project/mounted context, but NO
        ``next_action`` enum / decision-table contract (that closed enum IS the FSM the
        model-driven loop escapes). The per-step JSON output contract is appended by
        ``run_model_driven_turn`` itself; here we only supply the grounding context.

        ``prior_progress`` (when a previous attempt at this task ran) is a compact ledger of what the
        model already did, so a replan/resume continues instead of re-reading everything (residual②).
        ``project_guidance`` is the workspace's own AGENTS.md conventions, carried into the system
        prompt so the doer actually follows them (prompt-eval report rec #2)."""
        system_prompt = (
            "You are CoderAgent in a local-first autonomous development runtime.\n"
            "Drive the task to completion yourself: at each step call the tools you need, read the "
            "observations you get back, then decide the next step.\n"
            "Work like a careful engineer in an EXISTING codebase — these are always-on rules, not "
            "optional steps:\n"
            "- Understand before you change: read the target file(s) and the nearby code BEFORE you "
            "edit them. Do not write or patch a file you have not read this run — you will clobber "
            "or duplicate what is already there.\n"
            "- Match what is already there: follow the surrounding style, naming and structure, and "
            "REUSE existing helpers/utilities instead of reimplementing them. Before importing a "
            "library, confirm the project already uses it — do not add dependencies casually.\n"
            "- Stay in scope: do exactly what the task asks — no unrequested refactors, renames or "
            "extra features. Make the smallest change that satisfies the task contract and stay "
            "within write_scope.\n"
            "- Verify before you finish: after changing code, run the project's tests/checks "
            "(run_tests / run_command) and read the output. Do not assume a test framework — check "
            "what the project uses. Never report done without verification evidence.\n"
            "- Work efficiently: put independent tool calls in one step (batch them), and prefer the "
            "specialized tools (read_file / search_text / find_files) over ad-hoc shell for reading "
            "and searching.\n"
            "- Tool or command failures come back to you as observations — adapt and retry; a "
            "failure does not block you and does not require anyone's permission to continue.\n"
            "- Only finish (done=true, empty tool_calls) once the expected artifact exists AND you "
            "have verified it.\n"
            "- narration is one short sentence in the user's language (Chinese) describing THIS step."
        ) + self._methodology_guidance(runtime_context, can_delegate=can_delegate)
        # The workspace's own conventions are authoritative — carry AGENTS.md into the system prompt
        # (like Claude Code does with CLAUDE.md) so the doer follows the project's rules, not just the
        # generic ones. It is the user's own trusted file; absent it, the prompt is unchanged.
        if project_guidance:
            system_prompt += (
                "\n\nPROJECT GUIDANCE (from this workspace's AGENTS.md — these project conventions "
                "are authoritative; follow them, and prefer them over the generic rules above when "
                "they conflict):\n" + project_guidance
            )
        # First-class seed field, not buried in the optional-methodology tail: dogfood
        # run-20260718-0001 offered remember/recall in the surface + guidance and the doer used
        # them zero times in 26 calls — salience in the task seed is the cheapest next lever.
        memory_index = runtime_context.get("memory")
        memory_protocol = (
            "Before finishing: if this task surfaced a durable cross-task fact (a convention, "
            "a pitfall, a decision and its why), record it with remember — one short note, "
            "never file contents."
        )
        if isinstance(memory_index, list) and memory_index:
            memory_protocol += (
                f" The memory index in runtime_context has {len(memory_index)} known entries; "
                "when one looks relevant, fetch its full text with recall_memory before "
                "re-deriving it yourself."
            )
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
            "memory_protocol": memory_protocol,
            "project": project_config,
            "runtime_context": context_prompt_view(runtime_context),
            "available_tools": available_tools,
            "allowed_tools": task.get("allowed_tools", []),
            "methodology_skills": self._methodology_skills(runtime_context),
        }
        if prior_progress:
            payload["prior_progress"] = prior_progress
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    #: Cap on the AGENTS.md text carried into the doer prompt. Project conventions are usually well
    #: under this; the cap only stops a pathologically huge guidance file from bloating every turn.
    _PROJECT_GUIDANCE_MAX_CHARS = 12_000

    def _project_guidance(self, root: Path) -> str | None:
        """The workspace's own AGENTS.md conventions, bounded, for the doer prompt (rec #2). Same
        source of truth the persisted prompt_envelope reads (`root/AGENTS.md`) — the difference is
        this text actually reaches the model. None when absent/empty. Best-effort: a read error must
        never abort a task, so it degrades to no guidance rather than raising."""
        try:
            path = root / "AGENTS.md"
            if not path.is_file():
                return None
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not text:
            return None
        if len(text) > self._PROJECT_GUIDANCE_MAX_CHARS:
            text = (
                text[: self._PROJECT_GUIDANCE_MAX_CHARS].rstrip()
                + "\n… (AGENTS.md truncated here; read the file for the rest)"
            )
        return text

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
            "- When you learn something durable — an approach that failed and why, a repo/tool "
            "quirk, a decision and its reason — record it with remember so future runs start "
            "knowing it. Especially before finishing a goal. The memory index in your context "
            "lists what is already known; recall_memory fetches a truncated entry in full.",
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

    def _model_cost_for_task(self, context: RuntimeContext, task_id: str) -> dict:
        """What one task (or one delegated expert's child task) actually spent. Reads the model-call
        log, which since B7 carries the task_id that spent each call. Tokens — not the loop's
        iteration count — are the honest cost: an expert can burn a big context in few turns."""
        empty = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
        if context.run_dir is None or not task_id:
            return empty
        path = context.run_dir / "model_calls.jsonl"
        if not path.exists():
            return empty
        calls = 0
        input_tokens = 0
        output_tokens = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("task_id") or "") != task_id:
                continue
            calls += 1
            input_tokens += int(record.get("input_tokens") or 0)
            output_tokens += int(record.get("output_tokens") or 0)
        return {
            "model_calls": calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _record_model_driven_event(
        self,
        context: RuntimeContext,
        task: dict,
        event: TurnEvent,
        *,
        subagent_role: str | None = None,
    ) -> None:
        """Project 立真身 loop events onto the user progress stream: the model's narration/final
        message rides the main thread in its own voice (ADR-0021); tool observations land in the
        Inspector (evidence, not conversation). A DELEGATED expert's events carry ``subagent_role`` —
        its narration is the sub-task's evidence, not the lead's voice, so it stays in the Inspector;
        the lead only sees the returned summary on the main thread (spawn_subagent, ADR-0022 ③)."""
        task_id = str(task.get("task_id") or "")
        is_child = subagent_role is not None
        if event.kind in {"narration", "final"} and event.text:
            self._record_progress(
                context,
                task,
                channel="model",
                event_type="message",
                phase="execute",
                status="running",
                title=(
                    f"{subagent_role} 专家叙述"
                    if is_child
                    else ("模型叙述" if event.kind == "narration" else "模型收尾")
                ),
                summary=event.text,
                display_level="inspector" if is_child else "main",
                transcript_kind="assistant_message",
                data={
                    "task_id": task_id,
                    "iteration": event.iteration,
                    "model_driven_turn": True,
                    **({"subagent_role": subagent_role} if is_child else {}),
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
                    title=f"工具结果 · {obs.tool_name}" + ("" if obs.ok else " (失败)"),
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
                # todo_write is not "a tool the model ran" — it IS the model re-planning out loud
                # (Claude Code's TodoWrite is rendered as the plan, never as a raw tool row). The
                # generic observation above stays in the Inspector as evidence; the plan itself gets
                # a main-thread card carrying the items + WHY they changed. A child expert's todos
                # are its own scratchpad, not the lead's plan, so they stay in the Inspector.
                if obs.tool_name == "todo_write" and obs.ok and not is_child:
                    items = [
                        item for item in (obs.data.get("items") or []) if isinstance(item, dict)
                    ]
                    self._record_progress(
                        context,
                        task,
                        channel="progress",
                        event_type="message",
                        phase="execute",
                        status="running",
                        title="更新计划",
                        summary=str(obs.data.get("update_reason") or "").strip()
                        or f"模型把当前工作拆成 {len(items)} 步。",
                        display_level="main",
                        transcript_kind="todo_update",
                        data={
                            "task_id": task_id,
                            "iteration": event.iteration,
                            "todo_items": items,
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
        # ADR-0024 §5 #1: re-scan the workspace so THIS task sees files that EARLIER tasks in the same
        # run already wrote. ``workspace_files`` is captured once at run start (ContextLoader.load) and
        # otherwise frozen for the whole run, so a multi-task run had the doer blindly re-creating a
        # file a prior task had just produced. ``runtime_context`` here is already a per-task dict
        # ({**mounted_context, ...} from the worker lambda), so overwriting this key does not pollute
        # the shared run-level context. Best-effort: a scan error must never abort a task the run-start
        # load already succeeded for, so it is narrowly contained and the prior snapshot is kept.
        try:
            runtime_context["workspace_files"] = ContextLoader(
                context.root, self.validator
            ).workspace_files()
        except OSError:
            pass
        # S90 压缩真缩（主路径半边）：预算压力≥near_limit 时，把 grounding 里最重且**可再生**的
        # 段（workspace_files 的内容摘录，20×1200 字符）真的从下一轮 prompt 里去掉，只留路径清单
        # （防重复建文件的正是清单，不是摘录）。确定性边界，不做认知——要看内容模型自己 read_file。
        # 此前 _compact_boundary 算出的 droppable 无人应用（completion-reaudit-20260718 §3）。
        if context.budget and context.budget.usage.context_pressure_status in {
            "near_limit",
            "hard_stop",
            "exceeded",
        }:
            runtime_context["workspace_files"] = slim_workspace_files(
                runtime_context.get("workspace_files") or []
            )
            runtime_context["context_pressure_note"] = (
                "Context budget is under pressure: workspace file excerpts were elided from this "
                "grounding. The file inventory is intact; use read_file for any content you need."
            )
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

    def _user_paused_model_driven_task(
        self,
        *,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        rounds_completed: int,
        max_rounds: int,
        tool_calls: int = 0,
        verification_calls: int = 0,
    ) -> TaskExecutionSummary:
        """用户按下暂停：在回合边界干净停手，run 报 paused，可 resume。

        与人审暂停(_pause_model_driven_task)共用同一条通路，区别只在没有待批决策——所以不生成
        DecisionPoint、不动 TaskBoard(任务没失败，resume 会重跑它)。"""
        task_id = task["task_id"]
        run_dir = context.root / ".asteria" / "runs" / str(context.run_id)
        reason = pause_reason(run_dir)
        # 消费信号：留着它，下一次 resume 会在第一个回合边界立刻又暂停——一个永远起不来的 run。
        clear_pause(run_dir)
        summary = f"已在回合边界暂停（{reason}）。已完成的工作已保留，`asteria resume` 从这里继续。"
        self._record_agent_loop_run_summary(
            context=context,
            task_id=task_id,
            status="paused",
            exit_reason="paused",
            rounds_completed=rounds_completed,
            max_rounds=max_rounds,
            summary=summary,
            recommended_command="resume",
            latest_decision=None,
            latest_execution=None,
            latest_observation=None,
            evidence_refs=[],
        )
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="message",
            phase="execute",
            # 用户进度事件用 waiting_user 而不是新造一个 "paused":一个暂停的 run **就是在等用户**,
            # 这正是现成且准确的词。(loop summary 那层确实需要 paused —— 它要把"用户按了暂停"和
            # "在等一个决策"区分开。)
            status="waiting_user",
            title="已暂停",
            summary=summary,
            evidence_refs=[],
            transcript_kind="progress",
            ui_intent="needs_input",
            data={"task_id": task_id, "pause_reason": reason},
        )
        return TaskExecutionSummary(
            task_id=task_id,
            status="paused",
            summary=summary,
            tool_calls=tool_calls,
            verification_calls=verification_calls,
        )

    def _blocked_task_summary(
        self,
        result: BlockingResult,
        *,
        tool_calls: int = 0,
        verification_calls: int = 0,
    ) -> TaskExecutionSummary:
        # Counts default to 0 for genuine pre-work blocks (policy denial, runtime request before any
        # tool ran). The human-approval pause path passes the real pre-pause activity so a paused task
        # is not misreported as having done nothing.
        return TaskExecutionSummary(
            task_id=result.task_id,
            status=result.status,
            summary=result.summary,
            tool_calls=tool_calls,
            verification_calls=verification_calls,
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
        # Marks `shell` / `run_tests` as "ask" rather than "deny" on the model's tool surface.
        #
        # `auto` was missing from this set, which inverted the tiers: the MOST permissive mode was
        # the only one whose surface marked shell and tests denied. That never bit, and this is not
        # a live bug fix — the surface's `permission` field reaches nothing today (the model payload
        # carries tool *names* only, and enforcement lives in ToolExecutionGateway + the always-on
        # hard guards), so both tiers really do offer shell. It is corrected here so the inversion
        # cannot start biting the day that field is honoured. (The legacy strings that used to sit
        # in this set — allow / allow_all / trusted — are not values normalize_permission_mode can
        # produce, so they matched nothing either.)
        permission = str(policy.get("permission_mode") or "").lower()
        return permission in {"reviewed_auto", "auto"}

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


def _latest_verification_per_command(verification_results: list) -> list:
    """Judge a repair loop's verification on each command's LATEST outcome, not the cumulative
    pass/fail of every call across the whole task.

    To fix a bug the model MUST first run the failing test (red), then fix and re-run it (green):
    counting that mandatory initial red as a permanent failure made ``check_completion_contract``
    append ``verification did not pass`` (verification_passed != verification_total) and marked a
    genuinely fixed, verified-green task ``blocked`` — defeating the entire repair ring. The
    real-stack ``ring_recovery`` benchmark (2026-07-14) surfaced exactly this: glm ran pytest (fail)
    → fixed the code → ran pytest (pass), and was still blocked because the initial red counted.

    Dedup by the verification COMMAND keeping the LAST observation, so red→green on the SAME command
    passes, while a red test cannot be masked by later running a DIFFERENT passing command — that
    other command's latest is what counts, and the failing test's latest is still red (preserves the
    ring_val_f anti-gaming guard). Observations without a command (e.g. doc readbacks) pass through
    unchanged."""
    latest: dict[str, Any] = {}
    order: list[str] = []
    passthrough: list = []
    for obs in verification_results:
        data = getattr(obs, "data", {}) or {}
        command = str(data.get("requested_command") or data.get("command") or "").strip()
        if not command:
            passthrough.append(obs)
            continue
        if command not in latest:
            order.append(command)
        latest[command] = obs
    return passthrough + [latest[command] for command in order]


# The stop-guardrail and the completion contract must agree on what counts as a checkable file, or a
# task can be held open for an artifact one of them does not even consider a file. One predicate,
# defined next to the contract that enforces it (task_contract.looks_like_file_path).
_looks_like_path = looks_like_file_path


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
        # The reason, structured — so the loop can tell the user why it did not stop. The prompt text
        # above is written for the MODEL and is never shown as user-facing copy.
        facts={"missing_artifacts": missing},
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

    def __init__(
        self,
        gateway: Any,
        spawn: Callable[[dict], _SubagentResult],
        spawn_batch: Callable[[list[dict]], list[_SubagentResult]] | None = None,
    ) -> None:
        self._gateway = gateway
        self._spawn = spawn
        self._spawn_batch = spawn_batch

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: Any,
        stop_on_failure: bool = True,
        stop_verification_on_fatal: bool = False,
    ) -> list[Any]:
        # Collect the batch's spawn_subagent calls so they can fan out concurrently (ADR-0023),
        # while non-spawn tools still run serially through the frozen gateway (permissions / sandbox
        # / evidence intact). Results are reassembled into the model's original call order.
        spawn_indices = [
            index
            for index, call in enumerate(calls)
            if str(call.get("tool_name") or "") == "spawn_subagent"
        ]
        spawn_results: dict[int, Any] = {}
        if spawn_indices:
            spawn_args = [calls[index].get("args") or {} for index in spawn_indices]
            batched = (
                self._spawn_batch(spawn_args)
                if self._spawn_batch is not None
                else [self._spawn(args) for args in spawn_args]
            )
            spawn_results = dict(zip(spawn_indices, batched))

        results: list[Any] = []
        for index, call in enumerate(calls):
            if index in spawn_results:
                results.append(spawn_results[index])
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
