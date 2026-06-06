from __future__ import annotations

import copy

from asteria_runtime.core.swarm_flag_rollout import (
    REAL_DISJOINT_WRITE_FLAG,
    evaluate_rollout_readiness,
    evaluate_rollback_safety,
    flag_active_in_policy,
    maintainer_probe_environment,
    plan_flag_transition,
    with_feature_flag,
    with_maintainer_probe_policy,
)
from asteria_runtime.core.worker_spawn import plan_worker_spawns


def _base_policy(*, enabled: bool = False) -> dict:
    return {
        "feature_flags": {
            REAL_DISJOINT_WRITE_FLAG: {
                "enabled": enabled,
                "requires": ["real_model"],
            }
        }
    }


def test_rollout_blocked_without_capability_when_enabling() -> None:
    readiness = evaluate_rollout_readiness(_base_policy(), target_enabled=True)
    assert readiness.ready is False
    assert "capability_missing" in readiness.blockers


def test_rollout_ready_with_maintainer_probe_environment() -> None:
    readiness = evaluate_rollout_readiness(
        _base_policy(),
        target_enabled=True,
        environment=maintainer_probe_environment(),
    )
    assert readiness.ready is True


def test_plan_flag_transition_enable_safe_with_probe() -> None:
    plan = plan_flag_transition(
        _base_policy(),
        enable=True,
        environment=maintainer_probe_environment(),
    )
    assert plan.safe is True
    assert plan.to_enabled is True
    assert plan.rollback_policy["feature_flags"][REAL_DISJOINT_WRITE_FLAG]["enabled"] is False


def test_rollback_always_safe_after_enable() -> None:
    enabled_policy = with_feature_flag(_base_policy(), REAL_DISJOINT_WRITE_FLAG, enabled=True)
    rollback = evaluate_rollback_safety(enabled_policy, environment=maintainer_probe_environment())
    assert rollback.ready is True
    assert rollback.target_enabled is False


def test_maintainer_probe_policy_activates_flag() -> None:
    probe = with_maintainer_probe_policy(_base_policy())
    assert flag_active_in_policy(probe, environment=maintainer_probe_environment()) is True


def test_probe_policy_drives_parallel_spawn_plan() -> None:
    probe = with_maintainer_probe_policy(_base_policy())
    task = {
        "parallel_safety": "disjoint_writes",
        "write_scope": ["a.txt", "b.txt"],
        "multi_agent_strategy": {"mode": "disjoint_write_workers"},
    }
    plan = plan_worker_spawns(task, policy=probe, worker_count=2)
    assert plan.scheduling_mode == "parallel"
    assert plan.fake_path is False


def test_default_policy_stays_fake_serial() -> None:
    task = {
        "parallel_safety": "disjoint_writes",
        "write_scope": ["a.txt", "b.txt"],
    }
    plan = plan_worker_spawns(task, policy=_base_policy(), worker_count=2)
    assert plan.scheduling_mode == "fake_serial"
    assert plan.fake_path is True


def test_with_feature_flag_preserves_other_flags() -> None:
    policy = copy.deepcopy(_base_policy())
    policy["feature_flags"]["streaming"] = {"enabled": True}
    updated = with_feature_flag(policy, REAL_DISJOINT_WRITE_FLAG, enabled=True)
    assert updated["feature_flags"]["streaming"]["enabled"] is True
