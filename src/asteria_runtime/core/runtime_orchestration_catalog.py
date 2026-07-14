from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.execution_profile import execution_profile_from_run_config
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.run_config import load_run_config
from asteria_runtime.core.orchestration_spawn_policy import catalog_selection_guidance
from asteria_runtime.core.session_continuation import assess_session_continuation
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


CONTINUABLE_PHASES = frozenset({"ACCEPTED", "DONE", "REVIEW"})
IN_PROGRESS_STATUSES = frozenset({"running", "blocked", "paused", "in_progress"})


@dataclass(frozen=True)
class WorkspaceOrchestrationState:
    initialized: bool
    current_run_id: str | None = None
    run_status: str | None = None
    current_phase: str | None = None
    workflow_state: str | None = None
    recommended_next_command: str | None = None
    pending_decision_count: int = 0
    execution_profile_id: str = "session_agent"
    parallel_writes_enabled: bool = False
    spawn_parallel_workers_catalog_gray: bool = False
    dynamic_workflows_gray: bool = False
    session_continue_eligible: bool = False
    active_goal_memory_present: bool = False
    can_review: bool = False
    can_accept: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "initialized": self.initialized,
            "current_run_id": self.current_run_id,
            "run_status": self.run_status,
            "current_phase": self.current_phase,
            "workflow_state": self.workflow_state,
            "recommended_next_command": self.recommended_next_command,
            "pending_decision_count": self.pending_decision_count,
            "execution_profile_id": self.execution_profile_id,
            "parallel_writes_enabled": self.parallel_writes_enabled,
            "spawn_parallel_workers_catalog_gray": self.spawn_parallel_workers_catalog_gray,
            "dynamic_workflows_gray": self.dynamic_workflows_gray,
            "session_continue_eligible": self.session_continue_eligible,
            "active_goal_memory_present": self.active_goal_memory_present,
            "can_review": self.can_review,
            "can_accept": self.can_accept,
        }


@dataclass(frozen=True)
class OrchestrationCapability:
    capability_id: str
    layer: str
    title: str
    description: str
    when_to_use: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    cost_tier: str = "medium"
    risk_tier: str = "default"
    studio_mode: str = "chat"
    route_kind: str = "conversation"
    available: bool = True
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "layer": self.layer,
            "title": self.title,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "prerequisites": self.prerequisites,
            "cost_tier": self.cost_tier,
            "risk_tier": self.risk_tier,
            "studio_mode": self.studio_mode,
            "route_kind": self.route_kind,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class RuntimeOrchestrationCatalog:
    schema_version: str
    workspace: WorkspaceOrchestrationState
    capabilities: list[OrchestrationCapability]
    selection_guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace": self.workspace.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "selection_guidance": self.selection_guidance,
        }

    def available_capabilities(self) -> list[OrchestrationCapability]:
        return [item for item in self.capabilities if item.available]

    def get(self, capability_id: str) -> OrchestrationCapability | None:
        for item in self.capabilities:
            if item.capability_id == capability_id:
                return item
        return None


def load_workspace_orchestration_state(root: Path, *, validator: SchemaValidator) -> WorkspaceOrchestrationState:
    agent_dir = root / ".asteria"
    if not agent_dir.exists():
        return WorkspaceOrchestrationState(initialized=False)
    parallel_writes, catalog_gray, dynamic_gray = _load_orchestration_policy_flags(agent_dir, validator)
    run_store = RunStore(agent_dir, validator)
    run_id = run_store.current_session_id()
    if not run_id:
        memory = ActiveGoalMemory(root).read().strip()
        return WorkspaceOrchestrationState(
            initialized=True,
            parallel_writes_enabled=parallel_writes,
            spawn_parallel_workers_catalog_gray=catalog_gray,
            dynamic_workflows_gray=dynamic_gray,
            active_goal_memory_present=bool(memory),
        )
    run = run_store.load_run(run_id)
    run_dir = run_store.run_dir(run_id)
    phase = str(run.get("current_phase") or "").strip().upper()
    status = str(run.get("status") or "").strip().lower()
    profile = execution_profile_from_run_config(load_run_config(run_dir, validator))
    loop_summary = _read_optional_json(run_dir / "run_loop_summary.json")
    final_summary = _read_optional_json(run_dir / "final_report_summary.json")
    workflow_source = final_summary or loop_summary or {}
    workflow_state = str(workflow_source.get("workflow_state") or "")
    recommended = str(
        workflow_source.get("recommended_next_command")
        or run.get("recommended_next_command")
        or ""
    ).strip()
    pending = _pending_decision_count(run_dir, validator)
    continuation = assess_session_continuation(root, validator=validator)
    memory = ActiveGoalMemory(root).read().strip()
    can_review = "review" in recommended.lower() or workflow_state in {
        "ready_for_review",
        "review_pending",
    }
    can_accept = "accept" in recommended.lower() or workflow_state in {
        "ready_for_accept",
        "accepted",
    }
    return WorkspaceOrchestrationState(
        initialized=True,
        current_run_id=run_id,
        run_status=status or None,
        current_phase=phase or None,
        workflow_state=workflow_state or None,
        recommended_next_command=recommended or None,
        pending_decision_count=pending,
        execution_profile_id=profile.profile_id,
        parallel_writes_enabled=parallel_writes,
        spawn_parallel_workers_catalog_gray=catalog_gray,
        dynamic_workflows_gray=dynamic_gray,
        session_continue_eligible=continuation is not None,
        active_goal_memory_present=bool(memory),
        can_review=can_review,
        can_accept=can_accept,
    )


def build_runtime_orchestration_catalog(
    root: Path,
    *,
    validator: SchemaValidator,
    state: WorkspaceOrchestrationState | None = None,
) -> RuntimeOrchestrationCatalog:
    workspace = state or load_workspace_orchestration_state(root, validator=validator)
    capabilities = _base_capabilities(workspace)
    return RuntimeOrchestrationCatalog(
        schema_version="0.1.0",
        workspace=workspace,
        capabilities=capabilities,
        selection_guidance=catalog_selection_guidance(),
    )


def orchestration_catalog_prompt_block(catalog: RuntimeOrchestrationCatalog) -> str:
    lines = [
        "Runtime orchestration capabilities (choose one):",
        f"Workspace: {catalog.workspace.to_dict()}",
        "",
    ]
    for item in catalog.capabilities:
        flag = "available" if item.available else "unavailable"
        lines.append(f"- {item.capability_id} [{item.layer}] ({flag})")
        lines.append(f"  {item.title}: {item.description}")
        if item.when_to_use:
            lines.append("  When: " + "; ".join(item.when_to_use))
        if item.prerequisites:
            lines.append("  Requires: " + "; ".join(item.prerequisites))
        if not item.available and item.unavailable_reason:
            lines.append(f"  Blocked: {item.unavailable_reason}")
        lines.append("")
    lines.extend(catalog.selection_guidance)
    return "\n".join(lines)


def _base_capabilities(state: WorkspaceOrchestrationState) -> list[OrchestrationCapability]:
    # A run that has finished its execution loop and is waiting for the human to review or accept
    # (ready_for_review / ready_for_accept) is NOT actively in progress — it is idle-awaiting-human,
    # semantically like a completed run. Treating it as "in progress" was the goal-swallowing bug:
    # cold_goal_execute got blocked ("current run exists") so a brand-new user goal had no route
    # except resume_run, which folded the new goal into the stale run and replayed its result. A new
    # top-level message must always be able to start a fresh goal (Claude Code / Cursor never block a
    # new request on a pending review). So exclude awaiting-human runs from `in_progress`: this makes
    # cold_goal_execute / session_continue_execute available (both start a fresh run) and removes
    # resume_run (there is nothing to resume — the loop already finished). Genuinely running / blocked
    # / paused runs (not awaiting review) still count as in_progress and remain resumable.
    awaiting_human_review = bool(state.can_review or state.can_accept)
    in_progress = bool(
        state.current_run_id
        and state.current_phase not in CONTINUABLE_PHASES
        and (state.run_status or "") in IN_PROGRESS_STATUSES
        and not awaiting_human_review
    )
    cold_workspace = not state.current_run_id or (
        not in_progress and not state.session_continue_eligible
    )
    return [
        _cap(
            capability_id="chat_answer",
            layer="conversation",
            title="Answer in chat",
            description="Respond conversationally without starting or mutating a runtime run.",
            when_to_use=[
                "User asks a question, wants an explanation, travel/content plan, or runtime status in natural language.",
                "No workspace file changes are requested.",
            ],
            cost_tier="low",
            risk_tier="readonly",
            studio_mode="chat",
            route_kind="conversation",
            available=True,
        ),
        _cap(
            capability_id="read_only_plan",
            layer="orchestrator",
            title="Read-only development plan",
            description="Produce GoalSpec and task plan artifacts without executing changes.",
            when_to_use=[
                "User wants to understand scope, risks, or steps before editing files.",
                "Permission is not pre-approved for execution.",
            ],
            prerequisites=["Workspace initialized"],
            cost_tier="medium",
            risk_tier="readonly",
            studio_mode="plan",
            route_kind="read_only_plan",
            available=state.initialized,
            unavailable_reason=None if state.initialized else "Workspace is not initialized.",
        ),
        _cap(
            capability_id="cold_goal_execute",
            layer="orchestrator",
            title="Start a new controlled run",
            description="Run the full GoalSpec → Plan → Execute → Review path for a new goal.",
            when_to_use=[
                "User requests implementation work and no warm session continuation applies.",
                "This is the first coding change in the workspace or a genuinely new goal.",
            ],
            prerequisites=["Workspace initialized", "No warm continuation eligibility"],
            cost_tier="high",
            risk_tier="default",
            studio_mode="run",
            route_kind="cold_execute",
            available=state.initialized and cold_workspace and not in_progress,
            unavailable_reason=_blocked_reason(
                state.initialized and (cold_workspace and not in_progress),
                "Use session_continue_execute or resume_run when a current run already exists.",
            ),
        ),
        _cap(
            capability_id="session_continue_execute",
            layer="executor",
            title="Continue in current session",
            description="Reuse the accepted session run, append the follow-up instruction, and execute without replanning.",
            when_to_use=[
                "User asks for another small change in the same workspace after a completed or accepted run.",
                "Follow-up wording like continue, also, another tweak, add tests, fix regression.",
            ],
            prerequisites=["Current run accepted or completed", "session_agent profile"],
            cost_tier="medium",
            risk_tier="default",
            studio_mode="continue",
            route_kind="warm_session",
            available=state.session_continue_eligible,
            unavailable_reason=_blocked_reason(
                state.session_continue_eligible,
                "No accepted session run is available for warm continuation.",
            ),
        ),
        _cap(
            capability_id="resume_run",
            layer="coordinator",
            title="Resume current run",
            description="Continue the in-flight run loop, replay decisions, and execute ready tasks.",
            when_to_use=[
                "Current run is running, blocked, or paused.",
                "User says continue, resume, unblock, or proceed with the current task.",
            ],
            prerequisites=["Current run in progress", "No unresolved pending decisions"],
            cost_tier="medium",
            risk_tier="default",
            studio_mode="resume",
            route_kind="resume_in_progress",
            available=in_progress and state.pending_decision_count == 0,
            unavailable_reason=_blocked_reason(
                in_progress and state.pending_decision_count == 0,
                "No resumable in-progress run exists, or pending decisions must be resolved first.",
            ),
        ),
        _cap(
            capability_id="review_run",
            layer="verifier",
            title="Review current result",
            description="Run the review agent on the latest execution evidence.",
            when_to_use=["User asks to review, check quality, or validate the latest change."],
            prerequisites=["Run ready for review"],
            cost_tier="medium",
            risk_tier="readonly",
            studio_mode="review",
            route_kind="review",
            available=state.can_review,
            unavailable_reason=_blocked_reason(state.can_review, "Current run is not ready for review."),
        ),
        _cap(
            capability_id="accept_run",
            layer="verifier",
            title="Accept reviewed result",
            description="Accept the reviewed run and finalize the slice.",
            when_to_use=["User explicitly accepts the reviewed result."],
            prerequisites=["Review passed", "Run ready for accept"],
            cost_tier="low",
            risk_tier="readonly",
            studio_mode="accept",
            route_kind="accept",
            available=state.can_accept,
            unavailable_reason=_blocked_reason(state.can_accept, "Current run is not ready for accept."),
        ),
        _cap(
            capability_id="run_dynamic_orchestration",
            layer="L3_orchestrator",
            title="L3 dynamic workflow orchestration (designed, not yet built)",
            description=(
                "DESIGNED-NOT-BUILT: a manifest-driven multi-phase workflow (fanout, verifier, merge "
                "checkpoint) via an L3 runner. The runner and its verifier/adversarial/merge-checkpoint "
                "step-kinds are not implemented (no source); this is a frozen orchestration-band design "
                "(S61–S73 wave, frozen). Not routable. Real concurrent readonly fanout / disjoint writes "
                "already ship as AgentLoop subagent decisions—not this L3 manifest band."
            ),
            when_to_use=[
                "Goal explicitly requires multi-phase orchestration with checkpoints, resume, "
                "parallel readonly fanout, adversarial verifier, or disjoint write merge gates.",
                "User references workflow manifest, orchestration script, or resumable L3 band.",
                "Strong judgment: coordinated phases with merge evidence—not a single scoped edit.",
            ],
            prerequisites=[
                "orchestration_dynamic_workflows_gray maintainer policy enabled",
                "Wave 6+ L3 runner probe passed",
            ],
            cost_tier="high",
            risk_tier="high",
            studio_mode="orchestration",
            route_kind="dynamic_orchestration",
            available=_run_dynamic_orchestration_available(state),
            unavailable_reason=_blocked_reason(
                _run_dynamic_orchestration_available(state),
                "L3 dynamic orchestration is designed but not yet implemented (frozen band; "
                "runner + verifier/merge-checkpoint steps have no source).",
            ),
        ),
        _cap(
            capability_id="spawn_parallel_workers",
            layer="coordinator",
            title="Parallel worker dispatch (gray)",
            description=(
                "Start a harness run with Coordinator multi-worker dispatch. "
                "Only when strong routing judges the goal needs parallel exploration or disjoint writes "
                "with merge evidence—not for small or single-scope edits."
            ),
            when_to_use=[
                "Goal scope is large enough that parallel readonly exploration or disjoint write workers "
                "materially reduces time, and merge/promotion evidence is acceptable.",
                "Strong model judgment after reading workspace state; not keyword triggers or file counts.",
            ],
            prerequisites=[
                "Wave 2 probe passed or maintainer catalog_gray policy enabled",
                "Strong route judgment required to select this capability",
                "High-risk acceptance and merge gate",
            ],
            cost_tier="high",
            risk_tier="high",
            studio_mode="run",
            route_kind="parallel_dispatch",
            available=_spawn_parallel_workers_available(state),
            unavailable_reason=_blocked_reason(
                _spawn_parallel_workers_available(state),
                "Parallel dispatch is maintainer-only; beta default stays session_agent serial.",
            ),
        ),
    ]


def _spawn_parallel_workers_available(state: WorkspaceOrchestrationState) -> bool:
    """Catalog gray exposes ingress routing without enabling CLI parallel_writes default."""
    if state.spawn_parallel_workers_catalog_gray:
        return True
    return state.parallel_writes_enabled and state.execution_profile_id == "harness"


def _run_dynamic_orchestration_available(state: WorkspaceOrchestrationState) -> bool:
    """L3 ingress catalog entry; requires maintainer dynamic workflows gray."""
    return state.initialized and state.dynamic_workflows_gray


def _load_orchestration_policy_flags(
    agent_dir: Path,
    validator: SchemaValidator,
) -> tuple[bool, bool, bool]:
    policy = load_policy_config(agent_dir, validator)
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    parallel_writes = bool(agent_loop.get("parallel_writes"))
    catalog_gray = bool(agent_loop.get("spawn_parallel_workers_catalog_gray"))
    dynamic_gray = bool(agent_loop.get("orchestration_dynamic_workflows_gray"))
    return parallel_writes, catalog_gray, dynamic_gray


def _cap(**kwargs: Any) -> OrchestrationCapability:
    return OrchestrationCapability(**kwargs)


def _blocked_reason(ok: bool, reason: str) -> str | None:
    return None if ok else reason


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _pending_decision_count(run_dir: Path, validator: SchemaValidator) -> int:
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return 0
    pending = 0
    for decision in JsonlStore(validator).read_all(path, "decision_point"):
        if str(decision.get("status") or "") == "pending":
            pending += 1
    return pending
