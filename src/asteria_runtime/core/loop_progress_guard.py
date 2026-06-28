"""Agent-loop progress guard (loop_quality_guard consumer).

Purpose
-------
The bounded agent loop already has two *hard* fuses: ``max_rounds_per_task`` and the
budget hard-stop. What it lacked was an *auditable* read on whether the rounds it did
spend made provable progress, or whether the model spun on the same failing action.

Per ADR-0010 ("开放 Agent Loop；调用/repair 次数是 SLO，不是统一硬停止条件") and the
``agent_loop.loop_quality_guard`` policy (``mode: observe_then_warn``), this is an
observability / SLO instrument, **not** a kill-switch. It surfaces:

* ``repeated_failed_verifications`` — consecutive failed observations (window default 3),
* ``repeated_identical_observations`` — consecutive byte-identical no-progress
  observations (window default 8),

so loop health is visible to ``status``/Studio and can inform the rollout DecisionPoint.
A stricter ``mode`` could turn ``warn`` into a grounded stop in the future; the default
path only annotates and never overrides the model's recovery decision (ADR-0014).

This module is intentionally pure: it takes a list of agent-loop observations and a
config dict, and returns a signal. No IO, no policy resolution, no control flow.
"""

from __future__ import annotations

from typing import Any

# Mirrors agent_loop.loop_quality_guard in templates/policies.default.json. Kept here so
# the guard has sane defaults when a caller cannot thread the resolved policy through a
# DO_NOT_TOUCH boundary; an explicit ``config`` always wins.
DEFAULT_LOOP_QUALITY_GUARD: dict[str, Any] = {
    "enabled": True,
    "mode": "observe_then_warn",
    "repeated_identical_tool_window": 8,
    "repeated_failed_verification_window": 3,
    "hard_block_only_for_permission_or_destructive_risk": True,
}

_FAILED_STATUSES = {"failed"}
# Evidence refs that change every round even when no real work happened (the loop stamps
# a fresh execution/decision id on each observation). Excluded from the progress
# fingerprint so a genuine new artifact — a changed file or validation ref — is what
# distinguishes progress from a spin.
_VOLATILE_REF_PREFIXES = ("agent-loop-execution-", "agent-loop-decision-")


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_LOOP_QUALITY_GUARD)
    if isinstance(config, dict):
        merged.update({key: value for key, value in config.items() if value is not None})
    return merged


def observation_progress_fingerprint(observation: dict[str, Any]) -> str:
    """Stable signature for "the same work happened again".

    Any *real* progress changes this fingerprint: a new evidence ref (e.g. a changed
    file), a different failure summary, or a status transition. Two consecutive rounds
    with the same fingerprint are a provable no-progress repeat, not just a retry.
    """

    refs = sorted(
        str(ref)
        for ref in observation.get("evidence_refs") or []
        if not str(ref).startswith(_VOLATILE_REF_PREFIXES)
    )
    summary = " ".join(str(observation.get("summary") or "").split())
    return "|".join(
        [
            str(observation.get("observation_type") or ""),
            str(observation.get("status") or ""),
            summary,
            ";".join(refs),
        ]
    )


def _trailing_run(values: list[Any], predicate) -> int:
    count = 0
    for value in reversed(values):
        if predicate(value):
            count += 1
        else:
            break
    return count


def _trailing_identical_run(fingerprints: list[str]) -> int:
    if len(fingerprints) < 2:
        return 0
    last = fingerprints[-1]
    run = _trailing_run(fingerprints, lambda fp: fp == last)
    return run if run >= 2 else 0


def evaluate_loop_quality(
    observations: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Evaluate loop-quality over a task's agent-loop observations.

    Returns ``None`` only when the guard is disabled. Otherwise returns a signal dict
    (``warn`` is ``False`` for healthy loops) suitable for embedding in the agent-loop
    run summary as an auditable SLO field.
    """

    cfg = _merge_config(config)
    if not cfg.get("enabled", True):
        return None

    obs = [item for item in observations if isinstance(item, dict)]
    identical_window = max(1, int(cfg.get("repeated_identical_tool_window") or 8))
    failed_window = max(1, int(cfg.get("repeated_failed_verification_window") or 3))

    recent = obs[-identical_window:]
    fingerprints = [observation_progress_fingerprint(item) for item in recent]
    repeated_identical = _trailing_identical_run(fingerprints)
    repeated_failed = _trailing_run(
        obs, lambda item: str(item.get("status") or "") in _FAILED_STATUSES
    )

    identical_tripped = repeated_identical >= identical_window
    failed_tripped = repeated_failed >= failed_window
    warn = bool(identical_tripped or failed_tripped)

    reasons: list[str] = []
    if identical_tripped:
        reasons.append(
            f"{repeated_identical} consecutive identical no-progress observations "
            f"(window {identical_window})"
        )
    if failed_tripped:
        reasons.append(
            f"{repeated_failed} consecutive failed verifications (window {failed_window})"
        )
    reason = "; ".join(reasons) if reasons else "Loop progress within configured windows."

    return {
        "enabled": True,
        "mode": str(cfg.get("mode") or "observe_then_warn"),
        "observations_evaluated": len(obs),
        "repeated_identical_observations": repeated_identical,
        "repeated_identical_window": identical_window,
        "repeated_failed_verifications": repeated_failed,
        "repeated_failed_window": failed_window,
        "warn": warn,
        "severity": "warn" if warn else "ok",
        # observe_then_warn never hard-blocks; permission/destructive hard-blocks are
        # enforced at the action boundary, not here (ADR-0013).
        "hard_block": False,
        "reason": reason,
    }
