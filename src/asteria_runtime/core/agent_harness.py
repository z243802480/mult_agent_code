from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_role_policy import role_contracts_for_prompt
from asteria_runtime.core.agent_tool_surface import model_tool_surface, tool_surface_contract
from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class CapabilityTool:
    name: str
    kind: str
    permission: str
    description: str = ""
    sandbox_profile: str = "runtime_policy"
    read_scope: list[str] = field(default_factory=list)
    write_scope: list[str] = field(default_factory=list)
    cost_tier: str = "low"
    observation_schema: str = "tool_observation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "permission": self.permission,
            "permission_state": self.permission,
            "description": self.description,
            "sandbox_profile": self.sandbox_profile,
            "read_scope": self.read_scope,
            "write_scope": self.write_scope,
            "cost_tier": self.cost_tier,
            "observation_schema": self.observation_schema,
        }


@dataclass(frozen=True)
class CapabilityManifest:
    modes: list[str]
    tools: list[CapabilityTool]
    boundaries: dict[str, Any] = field(default_factory=dict)
    deferred_tools: list[CapabilityTool] = field(default_factory=list)
    mcp_tools: list[CapabilityTool] = field(default_factory=list)
    skills: list[CapabilityTool] = field(default_factory=list)
    subagents: list[CapabilityTool] = field(default_factory=list)
    verification: list[CapabilityTool] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": self.modes,
            "direct_tools": [tool.to_dict() for tool in self.tools],
            "deferred_tools": [tool.to_dict() for tool in self.deferred_tools],
            "mcp_tools": [tool.to_dict() for tool in self.mcp_tools],
            "skills": [tool.to_dict() for tool in self.skills],
            "subagents": [tool.to_dict() for tool in self.subagents],
            "verification": [tool.to_dict() for tool in self.verification],
            "tools": [tool.to_dict() for tool in self.tools],
            "boundaries": self.boundaries,
        }

    def prompt_summary(self) -> str:
        tool_lines = [
            f"- {tool.name}: {tool.kind}, permission={tool.permission}"
            for tool in self.tools
        ]
        boundary_lines = [
            f"- {key}: {value}" for key, value in sorted(self.boundaries.items())
        ]
        return "\n".join(
            [
                "Available modes: " + ", ".join(self.modes),
                "Direct tools:",
                *tool_lines,
                "Deferred tools: "
                + ", ".join(tool.name for tool in self.deferred_tools + self.mcp_tools),
                "Skills: " + ", ".join(tool.name for tool in self.skills),
                "Subagents: " + ", ".join(tool.name for tool in self.subagents),
                "Verification: " + ", ".join(tool.name for tool in self.verification),
                "Runtime boundaries:",
                *boundary_lines,
            ]
        )


@dataclass(frozen=True)
class PromptEnvelopeSection:
    name: str
    source: str
    priority: str
    cache_scope: str
    content: str
    evidence_refs: list[str] = field(default_factory=list)
    cache_break_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "priority": self.priority,
            "cache_scope": self.cache_scope,
            "token_estimate": _token_estimate(self.content),
            "content_hash": _content_hash(self.content),
            "summary": _summary(self.content),
            "evidence_refs": self.evidence_refs,
            "cache_break_reasons": self.cache_break_reasons,
        }


@dataclass(frozen=True)
class PromptEnvelope:
    run_id: str
    mode: str
    sections: list[PromptEnvelopeSection]
    capability_manifest: CapabilityManifest

    def to_dict(self) -> dict[str, Any]:
        section_dicts = [section.to_dict() for section in self.sections]
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "mode": self.mode,
            "sections": section_dicts,
            "section_order": [section.name for section in self.sections],
            "capability_manifest": self.capability_manifest.to_dict(),
            "content_hash": _content_hash(json.dumps(section_dicts, sort_keys=True)),
        }


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    ok: bool
    summary: str
    status: str
    error: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "ok": self.ok,
            "summary": self.summary,
            "status": self.status,
            "error": self.error,
            "artifact_refs": self.artifact_refs,
            "file_changes": self.file_changes,
            "telemetry": self.telemetry,
            "data": self.data,
        }

    def model_summary(self) -> str:
        state = "ok" if self.ok else "failed"
        error = f"; error={self.error}" if self.error else ""
        files = ""
        if self.file_changes:
            changed = [
                str(change.get("path"))
                for change in self.file_changes[:3]
                if change.get("path")
            ]
            if changed:
                files = "; files=" + ", ".join(changed)
        return f"{self.tool_name} {state}: {self.summary}{error}{files}"


def tool_observation_dict(result: Any) -> dict[str, Any] | None:
    observation = getattr(result, "harness_observation", None)
    if isinstance(observation, ToolObservation):
        return observation.to_dict()
    if isinstance(observation, dict):
        return observation
    return None


def tool_observation_summary(result: Any) -> str | None:
    observation = getattr(result, "harness_observation", None)
    if isinstance(observation, ToolObservation):
        return observation.model_summary()
    if isinstance(observation, dict):
        tool_name = str(observation.get("tool_name") or "tool")
        ok = bool(observation.get("ok"))
        state = "ok" if ok else "failed"
        summary = str(observation.get("summary") or "")
        error = f"; error={observation.get('error')}" if observation.get("error") else ""
        return f"{tool_name} {state}: {summary}{error}"
    return None


def harness_observation_record(
    *,
    task_id: str | None,
    stage: str | None,
    summary: str | None,
    observation: ToolObservation | dict[str, Any],
) -> dict[str, Any]:
    observation_dict = observation.to_dict() if isinstance(observation, ToolObservation) else observation
    return {
        "task_id": task_id,
        "stage": stage,
        "summary": summary or _observation_summary_from_dict(observation_dict),
        "observation": observation_dict,
    }


def load_harness_observations(run_dir: Path | None, *, limit: int = 12) -> list[dict[str, Any]]:
    if run_dir is None:
        return []
    path = run_dir / "user_progress.jsonl"
    if not path.exists():
        return []
    observations: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("channel") != "execution_chain":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        observation = data.get("observation") if isinstance(data, dict) else None
        if not isinstance(observation, dict):
            continue
        chain = event.get("execution_chain")
        task_id = chain[0] if isinstance(chain, list) and chain else None
        observations.append(
            harness_observation_record(
                task_id=task_id,
                stage=event.get("event_type"),
                summary=event.get("summary"),
                observation=observation,
            )
        )
    return observations[-limit:]


def load_raw_tool_observations(run_dir: Path | None, *, limit: int = 12) -> list[dict[str, Any]]:
    if run_dir is None:
        return []
    path = run_dir / "tool_observations.jsonl"
    if not path.exists():
        return []
    observations: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            observation = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(observation, dict):
            observations.append(observation)
    return observations[-limit:]


def tool_observation_action_options(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn failed tool observations into model-visible next-step choices."""
    return observation_next_action_plan(observations)["actions"]


def append_harness_observations(
    runtime_context: dict[str, Any],
    *,
    task_id: str | None,
    stage: str,
    results: list[Any],
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Append model-facing observations produced by tool results to runtime context."""
    observations = []
    for result in results:
        observation = tool_observation_dict(result)
        summary = tool_observation_summary(result)
        if not observation or not summary:
            continue
        observations.append(
            harness_observation_record(
                task_id=task_id,
                stage=stage,
                summary=summary,
                observation=observation,
            )
        )
    if not observations:
        return []
    existing = list(runtime_context.get("harness_observations") or [])
    runtime_context["harness_observations"] = [*existing, *observations][-limit:]
    return observations


def refresh_tool_observation_plan(
    runtime_context: dict[str, Any],
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh observation -> next-action plan in runtime context."""
    source = observations
    if source is None:
        source = [
            *list(runtime_context.get("tool_observations") or []),
            *list(runtime_context.get("harness_observations") or []),
        ]
    raw_observations = [_normalize_observation_for_plan(item) for item in list(source or [])]
    plan = observation_next_action_plan(raw_observations)
    runtime_context["observation_next_action_plan"] = plan
    runtime_context["tool_observation_actions"] = plan["actions"]
    return plan


def _normalize_observation_for_plan(observation: dict[str, Any]) -> dict[str, Any]:
    """Accept raw tool observations or harness records and return the flat observation body."""
    nested = observation.get("observation")
    if isinstance(nested, dict):
        merged = dict(nested)
        if observation.get("task_id") and "task_id" not in merged:
            merged["task_id"] = observation.get("task_id")
        return merged
    return observation


def persist_observation_next_action_plan(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    plan: dict[str, Any],
    run_id: str | None,
    task_id: str | None = None,
    trigger: str,
) -> dict[str, Any] | None:
    """Persist an observation plan for review/gate/Studio consumers."""
    if run_dir is None or not plan:
        return None
    failed_count = int(plan.get("failed_observation_count") or 0)
    if failed_count <= 0:
        return None
    path = run_dir / "observation_plans.jsonl"
    existing_count = len(JsonlStore(validator).read_all(path)) if path.exists() else 0
    record = {
        "schema_version": "0.1.0",
        "observation_plan_id": f"observation-plan-{existing_count + 1:04d}",
        "run_id": run_id,
        "task_id": task_id,
        "trigger": trigger,
        "failed_observation_count": failed_count,
        "actions": list(plan.get("actions") or []),
        "blockers": list(plan.get("blockers") or []),
        "evidence_refs": list(plan.get("evidence_refs") or []),
        "recommended_route": recommended_route_from_observation_plan(plan),
        "reason": observation_plan_reason(plan),
        "created_at": now_iso(),
    }
    JsonlStore(validator).append(path, record, "observation_plan")
    return record


def latest_observation_next_action_plan(
    run_dir: Path | None,
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "observation_plans.jsonl"
    if not path.exists():
        return None
    plans = JsonlStore(validator).read_all(path, "observation_plan")
    return plans[-1] if plans else None


def recommended_route_from_observation_plan(plan: dict[str, Any]) -> str:
    """Choose a safe high-level route from observation action candidates."""
    raw_actions = plan.get("actions")
    actions = raw_actions if isinstance(raw_actions, list) else []
    action_names = {str(action.get("action")) for action in actions if action.get("action")}
    raw_blockers = plan.get("blockers")
    blocker_items = raw_blockers if isinstance(raw_blockers, list) else []
    blockers = " ".join(str(item).lower() for item in blocker_items)
    if "ask" in action_names and any(
        signal in blockers
        for signal in ["permission", "scope", "credential", "runtime request", "decision"]
    ):
        return "ask"
    if "replan" in action_names and any(
        signal in blockers
        for signal in ["contract", "scope", "task", "expected", "read path", "write path"]
    ):
        return "replan"
    if "repair" in action_names and any(
        signal in blockers
        for signal in ["verification", "nonzero", "assert", "test", "unit", "tool failed"]
    ):
        return "repair"
    if "repair" in action_names:
        return "repair"
    if "replan" in action_names:
        return "replan"
    if "ask" in action_names:
        return "ask"
    if "stop" in action_names:
        return "stop"
    return "diagnose"


def observation_plan_reason(plan: dict[str, Any]) -> str:
    blockers = [str(item) for item in plan.get("blockers") or [] if item]
    route = recommended_route_from_observation_plan(plan)
    if blockers:
        return f"{route}: {blockers[0]}"
    return f"{route}: no blocker summary available"


def observation_next_action_plan(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize observations into a structured diagnose/repair/replan/ask/stop plan."""
    actions: list[dict[str, Any]] = []
    blockers: list[str] = []
    evidence_refs: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    failed = [observation for observation in observations if not observation.get("ok", True)]
    for observation in failed:
        tool_name = str(observation.get("tool_name") or "unknown")
        next_hint = str(observation.get("next_hint") or "diagnose_then_repair_replan_ask_or_stop")
        error_class = str(observation.get("error_class") or "unknown")
        summary = str(observation.get("summary") or observation.get("error") or "tool failed")
        blockers.append(f"{tool_name}: {summary}")
        for ref in observation.get("artifact_refs") or observation.get("evidence_refs") or []:
            evidence_refs.append(str(ref))
        for action in _actions_for_next_hint(next_hint, tool_name, error_class):
            key = (
                str(action.get("action")),
                str(action.get("tool_name")),
                str(action.get("error_class")),
            )
            if key in seen:
                continue
            action = {**action, "source_summary": summary}
            actions.append(action)
            seen.add(key)
    recommended = actions[0]["action"] if actions else "continue"
    return {
        "schema_version": "0.1.0",
        "status": "blocked" if failed else "ready",
        "failed_observation_count": len(failed),
        "recommended_action": recommended,
        "actions": actions,
        "blockers": blockers[:10],
        "evidence_refs": sorted(set(evidence_refs))[:10],
    }


def _actions_for_next_hint(
    next_hint: str,
    tool_name: str,
    error_class: str,
) -> list[dict[str, Any]]:
    if next_hint == "continue":
        return []
    if next_hint == "diagnose_then_repair_replan_ask_or_stop":
        return [
            {
                "action": "diagnose",
                "tool_name": tool_name,
                "error_class": error_class,
                "when": "The failure cause is still ambiguous.",
                "instruction": "Read the error and nearby evidence before changing files.",
            },
            {
                "action": "repair",
                "tool_name": tool_name,
                "error_class": error_class,
                "when": "The cause is understood and the fix is inside current scope.",
                "instruction": "Make the smallest scoped change, then verify.",
            },
            {
                "action": "replan",
                "tool_name": tool_name,
                "error_class": error_class,
                "when": "The task contract, scope, or decomposition is wrong.",
                "instruction": "Create or recommend a narrower follow-up task.",
            },
            {
                "action": "ask",
                "tool_name": tool_name,
                "error_class": error_class,
                "when": "Policy, scope, credentials, budget, or product direction needs approval.",
                "instruction": "Create a runtime request or DecisionPoint with concrete evidence.",
            },
            {
                "action": "stop",
                "tool_name": tool_name,
                "error_class": error_class,
                "when": "Continuing would hide failure or exceed guardrails.",
                "instruction": "Preserve evidence and report the blocker.",
            },
        ]
    return [
        {
            "action": next_hint,
            "tool_name": tool_name,
            "error_class": error_class,
            "when": "The observation provided a custom next_hint.",
            "instruction": "Use this hint only if it is consistent with policy and task scope.",
        }
    ]


def _observation_summary_from_dict(observation: dict[str, Any]) -> str:
    tool_name = str(observation.get("tool_name") or "tool")
    state = "ok" if observation.get("ok") else "failed"
    summary = str(observation.get("summary") or "")
    error = f"; error={observation.get('error')}" if observation.get("error") else ""
    return f"{tool_name} {state}: {summary}{error}"


@dataclass(frozen=True)
class HarnessTurnEvent:
    turn_id: str
    run_id: str | None
    task_id: str | None
    event_type: str
    summary: str
    observation: ToolObservation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "summary": self.summary,
            "observation": self.observation.to_dict() if self.observation else None,
        }


class AgentHarness:
    """Builds the model-visible capability envelope for agent-led work."""

    def __init__(self, policy: dict[str, Any], tool_names: list[str] | None = None) -> None:
        self.policy = policy
        self.tool_names = sorted(tool_names or [])

    def capability_manifest(self, mode: str = "build") -> CapabilityManifest:
        permissions = self.policy.get("permissions") or {}
        protected_paths = self.policy.get("protected_paths") or []
        role_contracts = role_contracts_for_prompt(self.policy)
        invocation_policy = CapabilityInvocationPolicy().for_goal(
            self._mode_intent(mode),
            permission_mode=str(self.policy.get("permission_mode") or "reviewed_auto"),
            risk=self._mode_risk(mode),
        )
        tools = self._direct_tools(permissions)
        tools.extend(self._registered_tools(permissions))
        direct_tools = self._dedupe_tools(tools)
        runtime_tool_names = [tool.name for tool in direct_tools]
        model_tools = model_tool_surface(
            runtime_tool_names,
            allow_shell=bool(permissions.get("allow_shell")),
        )
        deferred_tools = [
            CapabilityTool(
                "tool_search",
                "discover",
                "allow",
                "Discover deferred tools before exposing them to the model loop.",
                cost_tier="low",
            )
        ]
        mcp_tools = [
            CapabilityTool(
                "mcp",
                "external",
                "ask",
                "Use configured MCP tools only through runtime policy and audit logging.",
                cost_tier="medium",
            )
        ]
        skills = [
            CapabilityTool(
                "skill",
                "workflow",
                "allow",
                "Load task-specific workflow guidance and templates.",
                cost_tier="low",
            )
        ]
        subagents = [
            CapabilityTool(
                "subagent",
                "delegate",
                "ask",
                "Delegate bounded work with a goal, scope, permissions, and verification brief.",
                cost_tier="medium",
            )
        ]
        verification = [
            CapabilityTool(
                "run_tests",
                "verify",
                "ask" if permissions.get("allow_shell") else "deny",
                "Run bounded local verification commands and persist results.",
                cost_tier="medium",
            ),
            CapabilityTool(
                "review_agent",
                "verify",
                "ask",
                "Independently review non-trivial changes before final success claims.",
                cost_tier="medium",
            ),
            CapabilityTool(
                "merge_gate",
                "verify",
                "allow",
                "Check changed files, write scope, and verification evidence before promotion.",
                cost_tier="low",
            ),
        ]
        return CapabilityManifest(
            modes=["plan", "build", "review", "repair", "release"],
            tools=direct_tools,
            deferred_tools=deferred_tools,
            mcp_tools=mcp_tools,
            skills=skills,
            subagents=subagents,
            verification=verification,
            boundaries={
                "active_mode": mode,
                "protected_paths": protected_paths,
                "network": "allow" if permissions.get("allow_network") else "ask_or_deny",
                "shell": "allow" if permissions.get("allow_shell") else "deny",
                "destructive_shell": "allow" if permissions.get("allow_destructive_shell") else "deny",
                "remote_push": "allow" if permissions.get("allow_remote_push") else "deny",
                "writes": "candidate_workspace_preferred",
                "budget": "runtime_enforced",
                "role_contracts": role_contracts,
                "capability_invocation_policy": invocation_policy,
                "tool_surface_contract": tool_surface_contract(
                    runtime_tool_names,
                    allow_shell=bool(permissions.get("allow_shell")),
                ),
                "model_tool_surface": {
                    "schema_version": "0.1.0",
                    "adapter": "runtime_registry_to_model_primitives",
                    "tools": model_tools,
                    "guidance": [
                        "Prefer read/list/glob/grep/edit/run_tests before shell.",
                        "Use shell only when no dedicated primitive fits.",
                        "Todo tools are a model-facing planning surface and do not mutate task_plan.json.",
                    ],
                },
            },
        )

    def _mode_intent(self, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized == "research":
            return "research_goal"
        if normalized == "brainstorm":
            return "brainstorm_goal"
        return "implementation_goal"

    def _mode_risk(self, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized in {"review", "repair", "debug"}:
            return "high"
        if normalized in {"research", "plan"}:
            return "medium"
        return "medium"

    def prompt_envelope(
        self,
        *,
        run_id: str,
        mode: str = "build",
        project_guidance: str = "",
        project_guidance_refs: list[str] | None = None,
    ) -> PromptEnvelope:
        manifest = self.capability_manifest(mode=mode)
        permissions = self.policy.get("permissions") or {}
        budgets = self.policy.get("budgets") or {}
        sections = [
            PromptEnvelopeSection(
                "identity",
                "runtime",
                "system",
                "static",
                "You are Asteria Runtime OS, a local-first autonomous development runtime.",
            ),
            PromptEnvelopeSection(
                "operating_contract",
                "runtime",
                "system",
                "static",
                (
                    "Turn compact goals into verified artifacts through goal specification, "
                    "task decomposition, controlled tool use, validation, repair, context "
                    "compression, cost control, and final reporting."
                ),
            ),
            PromptEnvelopeSection(
                "project_guidance",
                "AGENTS.md",
                "project",
                "workspace",
                project_guidance or "No project guidance file was available.",
                project_guidance_refs or [],
                ["workspace_guidance_changed"],
            ),
            PromptEnvelopeSection(
                "capability_manifest",
                "AgentHarness",
                "system",
                "dynamic",
                manifest.prompt_summary(),
                cache_break_reasons=["tools_or_modes_changed", "permissions_changed"],
            ),
            PromptEnvelopeSection(
                "role_route_policy",
                "AgentHarness",
                "system",
                "dynamic",
                (
                    "Route and deadline decisions are role contracts, not raw command names. "
                    "GoalSpecAgent clarifies goals on strong route; PlannerAgent decomposes; "
                    "CoderAgent produces scoped candidates; DebugAgent consumes failed "
                    "observations; ReviewAgent independently verifies; ChatAgent answers or "
                    "routes product requests. Contracts: "
                    + json.dumps(role_contracts_for_prompt(self.policy), ensure_ascii=False)
                ),
                cache_break_reasons=["route_policy_changed", "deadline_policy_changed"],
            ),
            PromptEnvelopeSection(
                "tool_policy",
                "policy_config",
                "system",
                "dynamic",
                (
                    "Prefer read/search/file tools for local context, shell for bounded "
                    "verification or commands not expressible as structured tools, and "
                    "subagents only for broad exploration, independent implementation, "
                    "adversarial review, or context isolation."
                ),
                cache_break_reasons=["tool_registry_changed", "permissions_changed"],
            ),
            PromptEnvelopeSection(
                "safety_envelope",
                "policy_config",
                "system",
                "dynamic",
                (
                    "Protected paths, destructive shell actions, remote push, production "
                    f"deploy, and network-sensitive actions are governed by policy: {permissions}."
                ),
                cache_break_reasons=["permissions_changed"],
            ),
            PromptEnvelopeSection(
                "failure_repair",
                "runtime",
                "system",
                "static",
                (
                    "Treat failures as observations. Convert each failed ToolObservation into "
                    "one explicit next action: diagnose, repair, replan, ask, or stop. "
                    "Prefer diagnose when cause is ambiguous, repair only inside current scope, "
                    "replan when the task contract is wrong, ask for policy/scope/credential "
                    "approval, and stop when continuing would hide failure. Do not claim success "
                    "without evidence."
                ),
            ),
            PromptEnvelopeSection(
                "loop_decision_contract",
                "runtime",
                "system",
                "static",
                (
                    "Each agent loop turn must produce one AgentLoopDecision. "
                    "Allowed next_action.action values are tool, subagent, repair, "
                    "replan, ask, and stop. Every action must include reason, "
                    "target_task_id, capability_ref, expected_observation, risk, "
                    "budget_hint, and evidence_refs. Runtime validates this decision "
                    "before routing to tool gateway, subagent delegation, debug repair, "
                    "replan, DecisionPoint, or stop reporting."
                ),
            ),
            PromptEnvelopeSection(
                "delegation_contract",
                "runtime",
                "system",
                "static",
                (
                    "Child workers need a brief with goal, why, known context, files or "
                    "commands, constraints, allowed writes, expected output, and verification."
                ),
            ),
            PromptEnvelopeSection(
                "context_compaction",
                "policy_config",
                "system",
                "dynamic",
                (
                    "Context snapshots preserve goal, definition of done, accepted decisions, "
                    "active tasks, modified files, verification, failures, risks, and next actions."
                ),
                cache_break_reasons=["compaction_or_resume"],
            ),
            PromptEnvelopeSection(
                "user_communication",
                "runtime",
                "system",
                "dynamic",
                (
                    "Keep low-noise user progress visible: current phase, route, tool/model "
                    f"heartbeat, artifacts, evidence, and budget thresholds {budgets}."
                ),
                cache_break_reasons=["budget_threshold_changed"],
            ),
        ]
        return PromptEnvelope(
            run_id=run_id,
            mode=mode,
            sections=sections,
            capability_manifest=manifest,
        )

    def _direct_tools(self, permissions: dict[str, Any]) -> list[CapabilityTool]:
        shell_permission = "ask" if permissions.get("allow_shell") else "deny"
        return [
            CapabilityTool("read_file", "read", "allow", "Read files inside the workspace."),
            CapabilityTool("search", "read", "allow", "Search workspace text and filenames."),
            CapabilityTool("edit_file", "write", "ask", "Create or modify workspace files."),
            CapabilityTool("shell", "execute", shell_permission, "Run non-destructive shell commands."),
            CapabilityTool("run_tests", "verify", shell_permission, "Run bounded local verification."),
        ]

    def _registered_tools(self, permissions: dict[str, Any]) -> list[CapabilityTool]:
        shell_like = {"run_command", "run_tests"}
        write_like = {"write_file", "apply_patch"}
        planning_write = {"todo_write"}
        planning_read = {"todo_read"}
        tools: list[CapabilityTool] = []
        for name in self.tool_names:
            if name in shell_like:
                permission = "ask" if permissions.get("allow_shell") else "deny"
                kind = "execute"
            elif name in write_like:
                permission = "ask"
                kind = "write"
            elif name in planning_write:
                permission = "ask"
                kind = "planning"
            elif name in planning_read:
                permission = "allow"
                kind = "planning"
            else:
                permission = "allow"
                kind = "read"
            tools.append(CapabilityTool(name, kind, permission))
        return tools

    def _dedupe_tools(self, tools: list[CapabilityTool]) -> list[CapabilityTool]:
        by_name: dict[str, CapabilityTool] = {}
        for tool in tools:
            by_name[tool.name] = tool
        return [by_name[name] for name in sorted(by_name)]


def observation_from_tool_result(
    *,
    tool_name: str,
    result: Any,
    telemetry: dict[str, Any] | None = None,
    file_changes: list[dict[str, Any]] | None = None,
    artifact_refs: list[str] | None = None,
) -> ToolObservation:
    data = getattr(result, "data", None)
    safe_data = _observation_data(data)
    return ToolObservation(
        tool_name=tool_name,
        ok=bool(getattr(result, "ok", False)),
        summary=str(getattr(result, "summary", "")),
        status=str(getattr(result, "status", "") or ("success" if getattr(result, "ok", False) else "failure")),
        error=getattr(result, "error", None),
        artifact_refs=artifact_refs or _artifact_refs(tool_name, safe_data),
        file_changes=file_changes or [],
        telemetry=telemetry or {},
        data=safe_data,
    )


def observation_from_exception(
    *,
    tool_name: str,
    exc: Exception,
    telemetry: dict[str, Any] | None = None,
    file_changes: list[dict[str, Any]] | None = None,
) -> ToolObservation:
    return ToolObservation(
        tool_name=tool_name,
        ok=False,
        summary=str(exc),
        status="failure",
        error=str(exc),
        file_changes=file_changes or [],
        telemetry=telemetry or {},
        data={"error_type": exc.__class__.__name__},
    )


def _observation_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if key not in {"content", "diff"}
    }


def _artifact_refs(tool_name: str, data: dict[str, Any]) -> list[str]:
    if tool_name == "write_file" and data.get("path"):
        return [str(data["path"])]
    changed_files = data.get("changed_files")
    if isinstance(changed_files, list):
        return [str(path) for path in changed_files]
    return []


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _token_estimate(content: str) -> int:
    return max(1, (len(content) + 3) // 4) if content else 0


def _summary(content: str, max_chars: int = 280) -> str:
    compact = " ".join(content.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."
