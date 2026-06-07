"""Shared orchestration/spawn decision policy (CC-aligned, single source of truth).

Used by RuntimeOrchestrationCatalog, AgentHarness capability manifest, and route prompts.
Decisions are semantic (strong model + descriptions); not keyword or count heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpawnDecisionPolicy:
    """When strong models may choose subagent / parallel dispatch."""

    principles: list[str] = field(default_factory=list)
    subagent_when_to_use: list[str] = field(default_factory=list)
    subagent_when_not_to_use: list[str] = field(default_factory=list)
    studio_route_principles: list[str] = field(default_factory=list)
    parallel_dispatch_when_to_use: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "principles": list(self.principles),
            "subagent_when_to_use": list(self.subagent_when_to_use),
            "subagent_when_not_to_use": list(self.subagent_when_not_to_use),
            "studio_route_principles": list(self.studio_route_principles),
            "parallel_dispatch_when_to_use": list(self.parallel_dispatch_when_to_use),
            "deferred": list(self.deferred),
        }


SPAWN_DECISION_POLICY = SpawnDecisionPolicy(
    principles=[
        "High-stakes choices (Studio route, spawn, plan vs execute) use strong models reading capability descriptions.",
        "Cheap/medium tiers are for mechanical, repeatable, low-risk work—not orchestration or spawn decisions.",
        "Programs enforce availability, permissions, budget, schema, and merge gates—not NLU keyword routing.",
        "Prefer single session_agent path; collapse small goals to one task.",
        "Never spawn workers from keyword lists, file counts, or task counts.",
    ],
    subagent_when_to_use=[
        "Broad readonly exploration would flood the main context; fanout can return summaries.",
        "Independent verification or adversarial review must be isolated from the executor.",
        "Delegated scope is clear enough for a brief: goal, constraints, write scope, verification.",
        "Strong model judgment after reading task contract and manifest—not mechanical thresholds.",
    ],
    subagent_when_not_to_use=[
        "Single-file or small scoped edit completable with direct tools in one loop.",
        "Task contract already fits session_agent serial execution.",
        "User only asked a question or wants a plan without execution.",
        "Spawning would add merge/coordination cost without measurable benefit.",
    ],
    studio_route_principles=[
        "Studio ingress selects one capability from RuntimeOrchestrationCatalog (strong model).",
        "Default boundary path is session_agent via cold_goal_execute or session_continue_execute.",
        "chat_answer for conversation without file mutation.",
        "Subagent splits happen inside AgentLoop (subagent action), not at Studio ingress.",
    ],
    parallel_dispatch_when_to_use=[
        "Gray policy enables parallel_writes, catalog_gray, or harness profile AND strong route selects spawn_parallel_workers.",
        "Goal needs coordinated multi-worker dispatch with disjoint scopes and merge evidence.",
        "Research gate passed—see docs/zh/reports/S63-spawn-decision-research-20260607.md.",
    ],
    deferred=[
        "Mechanical multi-worker split at Studio ingress.",
        "Cheap model orchestration or spawn classification.",
        "CC Dynamic Workflows script engine transplant.",
        "Production parallel_writes without DecisionPoint and maintainer signoff.",
    ],
)


def catalog_selection_guidance() -> list[str]:
    return [
        "Pick exactly one capability_id from the available list.",
        "Default to the lightest path that fully satisfies intent; do not over-trigger full Harness.",
        "Prefer chat_answer for questions and discussion without file changes.",
        "Prefer read_only_plan when the user wants analysis or a plan before edits.",
        "Prefer session_continue_execute for follow-up edits in an accepted session.",
        "Prefer cold_goal_execute for a new implementation goal when no warm session applies.",
        "Prefer resume_run / review_run / accept_run only for clear lifecycle intent.",
        "Subagent and parallel exploration inside a run are AgentLoop subagent actions—not Studio ingress splits.",
        "Do not select spawn_parallel_workers unless available and strong judgment says coordinated multi-worker dispatch with merge evidence is required.",
        "Do not select run_dynamic_orchestration unless available and the goal requires multi-phase manifest orchestration with checkpoints—not for single small edits.",
        "Never split workers by keyword, file count, or task count.",
        "Do not select unavailable capabilities.",
    ]


def subagent_capability_description() -> str:
    return (
        "Delegate bounded work via AgentLoopDecision.subagent when strong model judgment "
        "requires context isolation, parallel readonly exploration, or independent verification."
    )


def subagent_manifest_extras() -> dict[str, list[str]]:
    policy = SPAWN_DECISION_POLICY
    return {
        "when_to_use": list(policy.subagent_when_to_use),
        "when_not_to_use": list(policy.subagent_when_not_to_use),
    }
