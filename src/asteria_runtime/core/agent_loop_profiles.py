from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.capability_catalog import task_capability_catalog
from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy
from asteria_runtime.core.runtime_profile import AgentLoopProfile


@dataclass(frozen=True)
class CapabilityRegistration:
    capability_id: str
    kind: str
    entrypoint: str
    loop_profile_id: str
    default_permission: str
    summary: str

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "entrypoint": self.entrypoint,
            "loop_profile_id": self.loop_profile_id,
            "default_permission": self.default_permission,
            "summary": self.summary,
        }


class AgentLoopProfileRegistry:
    def __init__(self) -> None:
        self._profiles = {
            "research": AgentLoopProfile(
                loop_profile_id="research",
                intent="research_goal",
                task_kinds=["research"],
                default_agents=["ResearchAgent"],
                capability_groups=["read_only_tools", "mcp_research", "runtime_context"],
                max_iterations=2,
                parallelism="readonly_fanout",
                stop_conditions=["sources_collected", "decision_required", "budget_limit"],
                summary="Collect bounded sources and synthesize claims before implementation.",
                output_contract={
                    "required": ["claims", "evidence_refs", "open_questions", "recommended_next_step"],
                    "artifact": "research_summary",
                    "user_visible_shape": "claims_with_evidence",
                },
                validation_contract={
                    "checks": [
                        "each material claim has evidence_refs",
                        "external source use follows MCP permission decision",
                        "open questions are explicit before implementation",
                    ],
                    "minimum_evidence_refs": 1,
                },
                failure_recovery={
                    "on_missing_sources": "ask_or_reduce_scope",
                    "on_mcp_denied": "continue_with_local_sources_and_record_limitation",
                    "on_budget_limit": "summarize_collected_sources_before_stop",
                },
                decision_escalation=[
                    "external source access is required",
                    "sources conflict on a decision-critical claim",
                    "research scope expands beyond the goal",
                ],
            ),
            "brainstorm": AgentLoopProfile(
                loop_profile_id="brainstorm",
                intent="brainstorm_goal",
                task_kinds=["brainstorm", "decision"],
                default_agents=["BrainstormAgent"],
                capability_groups=["read_only_tools", "runtime_context"],
                max_iterations=1,
                parallelism="serial",
                stop_conditions=["options_generated", "decision_required"],
                summary="Generate solution options without writing files or invoking external services.",
                output_contract={
                    "required": ["options", "tradeoffs", "recommended_option", "decision_point"],
                    "artifact": "brainstorm_options",
                    "user_visible_shape": "ranked_options",
                },
                validation_contract={
                    "checks": [
                        "at least two materially different options exist",
                        "recommendation includes tradeoff rationale",
                        "no write or external-service capability was used",
                    ],
                    "minimum_options": 2,
                },
                failure_recovery={
                    "on_thin_options": "ask_for_constraints_or_generate_more_candidates",
                    "on_write_requested": "deny_write_and_convert_to_decision_point",
                    "on_unclear_goal": "ask_for_decision_granularity",
                },
                decision_escalation=[
                    "recommended option changes product direction",
                    "tradeoffs depend on user appetite for risk or cost",
                ],
            ),
            "multi_agent": AgentLoopProfile(
                loop_profile_id="multi_agent",
                intent="implementation_goal",
                task_kinds=["implementation", "report", "configuration"],
                default_agents=["PlannerAgent", "CoderAgent", "ReviewAgent"],
                capability_groups=["direct_tools", "subagent", "verification", "merge_gate"],
                max_iterations=4,
                parallelism="bounded_workers",
                stop_conditions=["merge_gate_passed", "worker_blocked", "decision_required"],
                summary="Coordinate bounded workers for disjoint artifacts with merge-gate evidence.",
                output_contract={
                    "required": [
                        "worker_plan",
                        "worker_results",
                        "artifact_refs",
                        "merge_gate",
                        "final_report",
                    ],
                    "artifact": "multi_agent_execution_summary",
                    "user_visible_shape": "worker_progress_and_integrated_result",
                },
                validation_contract={
                    "checks": [
                        "worker write scopes are disjoint or explicitly coordinated",
                        "each promoted artifact has task execution evidence",
                        "merge gate is recorded before final success",
                    ],
                    "requires_merge_gate": True,
                },
                failure_recovery={
                    "on_worker_blocked": "repair_replan_or_ask_with_worker_evidence",
                    "on_write_conflict": "pause_for_merge_decision",
                    "on_merge_gate_failure": "record_blocker_and_do_not_promote",
                },
                decision_escalation=[
                    "workers need overlapping write scopes",
                    "merge gate blocks promotion",
                    "additional worker budget is required",
                ],
            ),
            "default": AgentLoopProfile(
                loop_profile_id="default",
                intent="implementation_goal",
                task_kinds=["implementation", "diagnostic", "verification", "review"],
                default_agents=["CoderAgent"],
                capability_groups=["direct_tools", "verification"],
                max_iterations=2,
                parallelism="serial",
                stop_conditions=["task_done", "blocked", "decision_required"],
                summary="Run a single controlled task loop with verification evidence.",
                output_contract={
                    "required": ["artifact_refs", "verification", "final_report"],
                    "artifact": "task_execution_summary",
                    "user_visible_shape": "result_with_verification",
                },
                validation_contract={
                    "checks": [
                        "expected artifacts are present",
                        "verification command or rationale is recorded",
                        "final report separates result and next action",
                    ],
                },
                failure_recovery={
                    "on_tool_failure": "diagnose_then_repair_replan_ask_or_stop",
                    "on_validation_failure": "repair_with_evidence",
                },
                decision_escalation=[
                    "permission is denied",
                    "task requires scope expansion",
                    "budget reaches hard stop",
                ],
            ),
        }
        self._registrations = [
            CapabilityRegistration(
                "research.sources",
                "runtime_command",
                "asteria research",
                "research",
                "ask",
                "Collect local or approved external research sources.",
            ),
            CapabilityRegistration(
                "brainstorm.options",
                "runtime_command",
                "asteria brainstorm",
                "brainstorm",
                "allow",
                "Generate option sets and optional DecisionPoints.",
            ),
            CapabilityRegistration(
                "multi_agent.workers",
                "runtime_layer",
                "AgentRunGraph + WorkerExecutionRecorder",
                "multi_agent",
                "ask",
                "Coordinate bounded child workers with promotion and merge gates.",
            ),
        ]

    def profiles(self) -> list[dict]:
        return [profile.to_dict() for profile in self._profiles.values()]

    def registrations(self) -> list[dict]:
        return [registration.to_dict() for registration in self._registrations]

    def for_task(self, task: dict, *, permission_mode: str = "reviewed_auto") -> dict:
        profile = self._profile_for_task(task)
        risk = self._risk_for_task(task)
        policy = CapabilityInvocationPolicy().for_task(
            intent=profile.intent,
            task_kind=str(task.get("task_kind") or profile.task_kinds[0]),
            permission_mode=permission_mode,
            risk=risk,
        )
        registrations = [
            registration.to_dict()
            for registration in self._registrations
            if registration.loop_profile_id == profile.loop_profile_id
        ]
        return {
            **profile.to_dict(),
            "capability_invocation_policy": policy,
            "registered_capabilities": registrations,
        }

    def dispatch_plan(
        self,
        tasks: list[dict],
        *,
        permission_mode: str = "reviewed_auto",
        runtime_tool_names: list[str] | None = None,
        skill_catalog: list[dict] | None = None,
        mcp_servers: list[dict] | None = None,
        allow_shell: bool = False,
    ) -> dict:
        profiles = [
            self.for_task(task, permission_mode=permission_mode)
            for task in tasks
            if isinstance(task, dict)
        ]
        counts: dict[str, int] = {}
        for profile in profiles:
            profile_id = str(profile["loop_profile_id"])
            counts[profile_id] = counts.get(profile_id, 0) + 1
        primary = self._primary_profile_id(counts)
        return {
            "schema_version": "0.1.0",
            "primary_loop_profile_id": primary,
            "profile_counts": counts,
            "task_dispatch": [
                {
                    "task_id": task.get("task_id"),
                    "task_kind": task.get("task_kind"),
                    "loop_profile_id": profile["loop_profile_id"],
                    "parallelism": profile["parallelism"],
                    "capability_groups": profile["capability_groups"],
                    "registered_capabilities": profile["registered_capabilities"],
                    "capability_invocation_policy": profile["capability_invocation_policy"],
                    "capability_catalog": task_capability_catalog(
                        task=task,
                        runtime_tool_names=runtime_tool_names or [],
                        permission_mode=permission_mode,
                        skill_catalog=skill_catalog or [],
                        mcp_servers=mcp_servers or [],
                        allow_shell=allow_shell,
                    ),
                    "output_contract": profile["output_contract"],
                    "validation_contract": profile["validation_contract"],
                    "failure_recovery": profile["failure_recovery"],
                    "decision_escalation": profile["decision_escalation"],
                    "dispatch_reason": profile["summary"],
                }
                for task, profile in zip(tasks, profiles, strict=False)
                if isinstance(task, dict)
            ],
            "available_loop_profiles": self.profiles(),
            "registered_capabilities": self.registrations(),
        }

    def _profile_for_task(self, task: dict) -> AgentLoopProfile:
        kind = str(task.get("task_kind") or "").lower()
        if kind == "research":
            return self._profiles["research"]
        if kind in {"brainstorm", "decision"}:
            return self._profiles["brainstorm"]
        strategy = task.get("multi_agent_strategy") or {}
        if isinstance(strategy, dict) and str(strategy.get("mode") or "serial") != "serial":
            return self._profiles["multi_agent"]
        return self._profiles["default"]

    def _primary_profile_id(self, counts: dict[str, int]) -> str:
        if not counts:
            return "default"
        priority = ["multi_agent", "research", "brainstorm", "default"]
        return sorted(
            counts,
            key=lambda item: (-counts[item], priority.index(item) if item in priority else 99),
        )[0]

    def _risk_for_task(self, task: dict) -> str:
        if task.get("risk") in {"low", "medium", "high"}:
            return str(task["risk"])
        if task.get("write_scope") or task.get("expected_changed_files"):
            return "medium"
        if str(task.get("task_kind") or "").lower() == "research":
            return "medium"
        return "low"
