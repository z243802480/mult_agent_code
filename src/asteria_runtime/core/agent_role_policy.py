from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentRoleContract:
    """Model route and deadline contract for one runtime role."""

    role: str
    purpose: str
    default_model_tier: str
    deadline_profile: str
    provider_call_seconds: int
    stream_idle_timeout_seconds: int
    max_model_calls: int
    responsibilities: list[str]
    escalation_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "purpose": self.purpose,
            "default_model_tier": self.default_model_tier,
            "deadline_profile": self.deadline_profile,
            "provider_call_seconds": self.provider_call_seconds,
            "stream_idle_timeout_seconds": self.stream_idle_timeout_seconds,
            "max_model_calls": self.max_model_calls,
            "responsibilities": self.responsibilities,
            "escalation_policy": self.escalation_policy,
        }


_ROLE_PURPOSES = {
    "goalspecagent": "goal_spec",
    "planneragent": "task_planning",
    "coderagent": "coding",
    "debugagent": "debugging",
    "reviewagent": "review",
    "researchagent": "research",
    "brainstormagent": "brainstorming",
    "chatagent": "chat",
    "modelcheckagent": "model_check",
    "modelcheckcommand": "model_check",
}


_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "goal_spec": {
        "role": "GoalSpecAgent",
        "tier": "strong",
        "deadline_profile": "strong_goal_spec",
        "provider_call_seconds": 120,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
        "responsibilities": [
            "clarify the user goal",
            "separate success criteria from implementation guesses",
            "choose whether to continue, ask, or stop before planning",
        ],
        "escalation_policy": "use strong by default; retry or downgrade only through provider_route_strategy",
    },
    "task_planning": {
        "role": "PlannerAgent",
        "tier": "strong",
        "deadline_profile": "planner",
        "provider_call_seconds": 90,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
        "responsibilities": [
            "decompose the goal into scoped tasks",
            "assign roles and write scopes",
            "create observable acceptance and validation expectations",
        ],
        "escalation_policy": "use strong for broad decomposition; downgrade only for doc-only low-risk plans",
    },
    "coding": {
        "role": "CoderAgent",
        "tier": "medium",
        "deadline_profile": "worker",
        "provider_call_seconds": 90,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
        "responsibilities": [
            "produce scoped candidate changes",
            "keep edits inside write scope",
            "return artifacts and verification commands",
        ],
        "escalation_policy": "start medium; escalate to strong on capability feedback, high risk, or complex scope",
    },
    "debugging": {
        "role": "DebugAgent",
        "tier": "medium",
        "deadline_profile": "repair",
        "provider_call_seconds": 75,
        "stream_idle_timeout_seconds": 25,
        "max_model_calls": 1,
        "responsibilities": [
            "diagnose failed evidence",
            "choose repair, replan, ask, or stop",
            "avoid blind retries without new evidence",
        ],
        "escalation_policy": "start medium; escalate when failures are ambiguous or repeated",
    },
    "review": {
        "role": "ReviewAgent",
        "tier": "strong",
        "deadline_profile": "review",
        "provider_call_seconds": 90,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
        "responsibilities": [
            "consume independent verification evidence",
            "summarize risk and release readiness",
            "refuse self-certified success for non-trivial changes",
        ],
        "escalation_policy": "use strong for release-impacting review; downgrade only for read-only summaries",
    },
    "research": {
        "role": "ResearchAgent",
        "tier": "cheap",
        "deadline_profile": "research",
        "provider_call_seconds": 60,
        "stream_idle_timeout_seconds": 20,
        "max_model_calls": 1,
        "responsibilities": [
            "collect and summarize bounded context",
            "avoid writes",
            "return sources and uncertainty",
        ],
        "escalation_policy": "stay cheap/medium unless the result drives architecture or release decisions",
    },
    "brainstorming": {
        "role": "BrainstormAgent",
        "tier": "strong",
        "deadline_profile": "planner",
        "provider_call_seconds": 75,
        "stream_idle_timeout_seconds": 25,
        "max_model_calls": 1,
        "responsibilities": [
            "generate divergent solution candidates",
            "score options for feasibility, cost, risk, and value",
            "convert the recommendation into candidate tasks and decisions",
        ],
        "escalation_policy": "use strong for product direction exploration; downgrade only for low-risk local sketches",
    },
    "chat": {
        "role": "ChatAgent",
        "tier": "medium",
        "deadline_profile": "interactive",
        "provider_call_seconds": 45,
        "stream_idle_timeout_seconds": 15,
        "max_model_calls": 1,
        "responsibilities": [
            "answer ordinary questions",
            "route tool or file-changing requests into the runtime workflow",
            "avoid exposing backend-only state in product workspace",
        ],
        "escalation_policy": "prefer responsive medium route; escalate only for planning-quality answers",
    },
    "model_check": {
        "role": "ModelCheckAgent",
        "tier": "cheap",
        "deadline_profile": "model_check",
        "provider_call_seconds": 30,
        "stream_idle_timeout_seconds": 10,
        "max_model_calls": 1,
        "responsibilities": [
            "probe provider configuration",
            "verify JSON response and streaming telemetry",
            "return route readiness evidence without consuming long-task budget",
        ],
        "escalation_policy": "use the requested route tier for the probe; keep deadline short and fail fast",
    },
}


def role_contract_for(
    *,
    role: str | None = None,
    purpose: str | None = None,
    policy: dict[str, Any] | None = None,
) -> AgentRoleContract:
    selected_purpose = _purpose_for_role_or_hint(role, purpose)
    defaults = _ROLE_DEFAULTS.get(selected_purpose, _ROLE_DEFAULTS["coding"])
    strategy = _deadline_strategy(policy or {}, defaults["deadline_profile"])
    return AgentRoleContract(
        role=str(role or defaults["role"]),
        purpose=selected_purpose,
        default_model_tier=str(defaults["tier"]),
        deadline_profile=str(defaults["deadline_profile"]),
        provider_call_seconds=int(
            strategy.get("provider_call_seconds") or defaults["provider_call_seconds"]
        ),
        stream_idle_timeout_seconds=int(
            strategy.get("stream_idle_timeout_seconds") or defaults["stream_idle_timeout_seconds"]
        ),
        max_model_calls=int(strategy.get("max_model_calls") or defaults["max_model_calls"]),
        responsibilities=list(defaults["responsibilities"]),
        escalation_policy=str(defaults["escalation_policy"]),
    )


def role_contracts_for_prompt(policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        role_contract_for(purpose=purpose, policy=policy).to_dict()
        for purpose in (
            "goal_spec",
            "task_planning",
            "coding",
            "debugging",
            "review",
            "research",
            "brainstorming",
            "chat",
            "model_check",
        )
    ]


def _purpose_for_role_or_hint(role: str | None, purpose: str | None) -> str:
    hinted = str(purpose or "").strip()
    if hinted in _ROLE_DEFAULTS:
        return hinted
    key = str(role or "").strip().lower().replace("_", "").replace("-", "")
    return _ROLE_PURPOSES.get(key, "coding")


def _deadline_strategy(policy: dict[str, Any], profile: str) -> dict[str, int]:
    defaults = {
        "provider_call_seconds": 90,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
    }
    if profile == "strong_goal_spec":
        route_strategy = policy.get("provider_route_strategy")
        route_strategy = route_strategy if isinstance(route_strategy, dict) else {}
        strong_goal_spec = route_strategy.get("strong_goal_spec")
        strong_goal_spec = strong_goal_spec if isinstance(strong_goal_spec, dict) else {}
        return {
            "provider_call_seconds": int(
                strong_goal_spec.get("provider_deadline_seconds")
                or _ROLE_DEFAULTS["goal_spec"]["provider_call_seconds"]
            ),
            "stream_idle_timeout_seconds": int(
                strong_goal_spec.get("stream_idle_timeout_seconds")
                or _ROLE_DEFAULTS["goal_spec"]["stream_idle_timeout_seconds"]
            ),
            "max_model_calls": int(strong_goal_spec.get("max_model_calls") or 1),
        }
    runtime_deadlines = policy.get("runtime_deadlines")
    runtime_deadlines = runtime_deadlines if isinstance(runtime_deadlines, dict) else {}
    profile_policy = runtime_deadlines.get(profile)
    profile_policy = profile_policy if isinstance(profile_policy, dict) else {}
    return {
        "provider_call_seconds": int(
            profile_policy.get("provider_call_seconds")
            or _ROLE_DEFAULTS.get(_purpose_from_deadline_profile(profile), defaults).get(
                "provider_call_seconds", defaults["provider_call_seconds"]
            )
        ),
        "stream_idle_timeout_seconds": int(
            profile_policy.get("stream_idle_timeout_seconds")
            or _ROLE_DEFAULTS.get(_purpose_from_deadline_profile(profile), defaults).get(
                "stream_idle_timeout_seconds", defaults["stream_idle_timeout_seconds"]
            )
        ),
        "max_model_calls": int(profile_policy.get("max_model_calls") or defaults["max_model_calls"]),
    }


def _purpose_from_deadline_profile(profile: str) -> str:
    return {
        "planner": "task_planning",
        "worker": "coding",
        "repair": "debugging",
        "review": "review",
        "research": "research",
        "brainstorming": "brainstorming",
        "interactive": "chat",
        "model_check": "model_check",
    }.get(profile, "coding")
