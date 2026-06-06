from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from asteria_runtime.core.flag_resolver import FlagResolver
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker_spawn import REAL_DISJOINT_WRITE_FLAG, real_disjoint_write_workers_active


MAINTAINER_PROBE_CAPABILITY = "maintainer_probe_mode"


@dataclass(frozen=True)
class RolloutPrerequisite:
    name: str
    ok: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "reason": self.reason}


@dataclass(frozen=True)
class RolloutReadinessResult:
    flag_name: str
    ready: bool
    current_active: bool
    target_enabled: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_name": self.flag_name,
            "ready": self.ready,
            "current_active": self.current_active,
            "target_enabled": self.target_enabled,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
        }


@dataclass(frozen=True)
class FlagTransitionPlan:
    flag_name: str
    from_enabled: bool
    to_enabled: bool
    safe: bool
    policy_after: dict[str, Any]
    rollback_policy: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_name": self.flag_name,
            "from_enabled": self.from_enabled,
            "to_enabled": self.to_enabled,
            "safe": self.safe,
            "reason": self.reason,
        }


def maintainer_probe_environment(*, real_model_available: bool = True) -> dict[str, bool]:
    """Capability environment for maintainer-only probes (not production Beta)."""
    return {
        "real_model_available": real_model_available,
        "maintainer_probe_mode": True,
    }


def with_maintainer_probe_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Return policy with flag enabled and maintainer probe capability for isolated drills."""
    base = copy.deepcopy(policy or {})
    updated = with_feature_flag(base, REAL_DISJOINT_WRITE_FLAG, enabled=True)
    caps = dict(updated.get("capability_flags") or {})
    caps[MAINTAINER_PROBE_CAPABILITY] = {
        "available": True,
        "reason": "Maintainer isolated disjoint probe.",
    }
    caps["real_model"] = {
        "available": True,
        "reason": "Maintainer probe satisfies real_model gate in isolated run_dir.",
    }
    updated["capability_flags"] = caps
    return updated


def with_feature_flag(policy: dict[str, Any], flag_name: str, *, enabled: bool) -> dict[str, Any]:
    updated = copy.deepcopy(policy)
    flags = dict(updated.get("feature_flags") or {})
    current = flags.get(flag_name)
    if isinstance(current, dict):
        flags[flag_name] = {**current, "enabled": enabled}
    else:
        flags[flag_name] = {"enabled": enabled}
    updated["feature_flags"] = flags
    return updated


def evaluate_rollout_readiness(
    policy: dict[str, Any] | None,
    *,
    target_enabled: bool,
    environment: dict[str, bool] | None = None,
    phase5_entry_signed: bool = True,
) -> RolloutReadinessResult:
    """Evaluate whether real_disjoint_write_workers may transition to target_enabled."""
    policy = policy or {}
    env = dict(environment or {})
    resolver = FlagResolver.from_policy(policy, environment=env)
    resolution = resolver.resolve(REAL_DISJOINT_WRITE_FLAG)
    current_active = resolution is not None and resolution.active

    prerequisites: list[RolloutPrerequisite] = []
    blockers: list[str] = []

    prerequisites.append(
        RolloutPrerequisite(
            "phase5_entry_signed",
            phase5_entry_signed,
            "Phase 5 entry (S18–S21) must be signed before rollout."
            if phase5_entry_signed
            else "Phase 5 entry signoff missing.",
        )
    )
    if not phase5_entry_signed:
        blockers.append("phase5_entry_unsigned")

    flag_configured = REAL_DISJOINT_WRITE_FLAG in (policy.get("feature_flags") or {})
    prerequisites.append(
        RolloutPrerequisite(
            "flag_configured",
            flag_configured,
            f"{REAL_DISJOINT_WRITE_FLAG} present in policy."
            if flag_configured
            else f"{REAL_DISJOINT_WRITE_FLAG} missing from policy feature_flags.",
        )
    )
    if not flag_configured:
        blockers.append("flag_not_configured")

    if target_enabled:
        probe_mode = env.get(MAINTAINER_PROBE_CAPABILITY, False)
        real_model = env.get("real_model_available", False)
        capability_ok = probe_mode or real_model
        prerequisites.append(
            RolloutPrerequisite(
                "capability_gate",
                capability_ok,
                "Maintainer probe or real_model capability required to enable flag."
                if capability_ok
                else "Enable requires maintainer_probe_mode or real_model_available.",
            )
        )
        if not capability_ok:
            blockers.append("capability_missing")

        if resolution is not None and resolution.flag.enabled and not current_active:
            prerequisites.append(
                RolloutPrerequisite(
                    "flag_resolution",
                    False,
                    resolution.reason,
                )
            )
            blockers.append("flag_resolution_blocked")
    else:
        prerequisites.append(
            RolloutPrerequisite(
                "rollback_always_safe",
                True,
                "Disabling flag returns to fake_serial / session_agent safe defaults.",
            )
        )

    ready = not blockers and all(item.ok for item in prerequisites)
    return RolloutReadinessResult(
        flag_name=REAL_DISJOINT_WRITE_FLAG,
        ready=ready,
        current_active=current_active,
        target_enabled=target_enabled,
        prerequisites=prerequisites,
        blockers=blockers,
    )


def plan_flag_transition(
    policy: dict[str, Any] | None,
    *,
    enable: bool,
    environment: dict[str, bool] | None = None,
    phase5_entry_signed: bool = True,
) -> FlagTransitionPlan:
    policy = policy or {}
    readiness = evaluate_rollout_readiness(
        policy,
        target_enabled=enable,
        environment=environment,
        phase5_entry_signed=phase5_entry_signed,
    )
    flags = policy.get("feature_flags") or {}
    raw = flags.get(REAL_DISJOINT_WRITE_FLAG)
    from_enabled = bool(raw.get("enabled", False)) if isinstance(raw, dict) else bool(raw)
    policy_after = with_feature_flag(policy, REAL_DISJOINT_WRITE_FLAG, enabled=enable)
    rollback_policy = with_feature_flag(policy_after, REAL_DISJOINT_WRITE_FLAG, enabled=False)
    safe = readiness.ready if enable else True
    reason = (
        f"Transition {REAL_DISJOINT_WRITE_FLAG}: {from_enabled} → {enable}."
        if safe
        else f"Blocked: {'; '.join(readiness.blockers)}"
    )
    return FlagTransitionPlan(
        flag_name=REAL_DISJOINT_WRITE_FLAG,
        from_enabled=from_enabled,
        to_enabled=enable,
        safe=safe,
        policy_after=policy_after,
        rollback_policy=rollback_policy,
        reason=reason,
    )


def evaluate_rollback_safety(
    policy: dict[str, Any] | None,
    *,
    environment: dict[str, bool] | None = None,
) -> RolloutReadinessResult:
    """After a probe, verify disabling the flag is safe."""
    return evaluate_rollout_readiness(
        policy,
        target_enabled=False,
        environment=environment,
        phase5_entry_signed=True,
    )


def flag_active_in_policy(policy: dict[str, Any] | None, *, environment: dict[str, bool] | None = None) -> bool:
    if not policy:
        return False
    if environment:
        resolver = FlagResolver.from_policy(policy, environment=environment)
        resolution = resolver.resolve(REAL_DISJOINT_WRITE_FLAG)
        return resolution is not None and resolution.active
    return real_disjoint_write_workers_active(policy)


def record_flag_transition(
    context: RuntimeContext,
    plan: FlagTransitionPlan,
    *,
    readiness: RolloutReadinessResult | None = None,
    actor: str = "SwarmFlagRollout",
) -> None:
    if context.event_logger is None:
        return
    payload: dict[str, Any] = {
        "transition": plan.to_dict(),
        "readiness": readiness.to_dict() if readiness else None,
    }
    context.event_logger.record(
        context.run_id,
        "swarm_flag_transition_planned",
        actor,
        plan.reason,
        payload,
    )
