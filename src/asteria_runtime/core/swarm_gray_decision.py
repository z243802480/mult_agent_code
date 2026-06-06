from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.swarm_flag_rollout import (
    REAL_DISJOINT_WRITE_FLAG,
    FlagTransitionPlan,
    RolloutReadinessResult,
    evaluate_rollback_safety,
    evaluate_rollout_readiness,
    maintainer_probe_environment,
    plan_flag_transition,
    record_flag_transition,
    with_feature_flag,
)
from asteria_runtime.core.swarm_pipeline import run_maintainer_real_disjoint_probe
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


GRAY_DECISION_KIND = "swarm_gray_rollout"
_DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "templates" / "policies.default.json"


def _gray_drill_base_policy(policy: dict | None) -> dict[str, Any]:
    if policy:
        return policy
    return json.loads(_DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class GrayRollbackDrillResult:
    ok: bool
    enable_readiness: RolloutReadinessResult
    rollback_readiness: RolloutReadinessResult
    enable_plan: FlagTransitionPlan
    rollback_plan: FlagTransitionPlan
    decision_point: dict[str, Any]
    probe_run_id: str
    probe_ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "probe_run_id": self.probe_run_id,
            "probe_ok": self.probe_ok,
            "summary": self.summary,
            "enable_readiness": self.enable_readiness.to_dict(),
            "rollback_readiness": self.rollback_readiness.to_dict(),
            "enable_plan": self.enable_plan.to_dict(),
            "rollback_plan": self.rollback_plan.to_dict(),
            "decision_point_id": self.decision_point.get("decision_id"),
            "checks": self.checks,
        }


def build_gray_enable_decision_point(*, run_id: str, sequence: int = 1) -> dict[str, Any]:
    """DecisionPoint template for maintainer gray enable (does not auto-enable production flag)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": f"decision-swarm-gray-{max(1, sequence):04d}",
        "status": "pending",
        "question": (
            "Enable real_disjoint_write_workers for an isolated maintainer probe? "
            "Beta default remains session_agent; CLI parallel_writes stays off."
        ),
        "recommended_option_id": "enable_isolated_probe",
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "enable_isolated_probe",
                "label": "Enable isolated maintainer probe",
                "tradeoff": "Runs probe in isolated run_dir; requires rollback after drill.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep flag disabled",
                "tradeoff": "Continue fake_serial / session_agent defaults.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Rollback to disabled",
                "tradeoff": "Force flag off and record rollback evidence.",
                "action": "cancel_scope",
            },
        ],
        "impact": {
            "scope": "high",
            "budget": "medium",
            "risk": "high",
            "quality": "medium",
        },
        "selected_option_id": None,
        "created_at": now_iso(),
        "metadata": {
            "kind": GRAY_DECISION_KIND,
            "run_id": run_id,
            "flag_name": REAL_DISJOINT_WRITE_FLAG,
            "requires_maintainer_approval": True,
            "cli_parallel_writes_unchanged": True,
        },
        "resolved_at": None,
    }


def persist_gray_decision_point(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    run_id: str,
) -> dict[str, Any]:
    path = run_dir / "decisions.jsonl"
    store = JsonlStore(validator)
    existing = store.read_all(path, "decision_point") if path.exists() else []
    decision = build_gray_enable_decision_point(run_id=run_id, sequence=len(existing) + 1)
    store.append(path, decision, "decision_point")
    return decision


def run_gray_rollback_drill(
    *,
    root: Path,
    run_dir: Path,
    run_id: str,
    validator: SchemaValidator,
    policy: dict | None = None,
) -> GrayRollbackDrillResult:
    """Maintainer drill: DecisionPoint → isolated probe → rollback audit (no production enable)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    base_policy = _gray_drill_base_policy(policy)
    env = maintainer_probe_environment()
    enable_readiness = evaluate_rollout_readiness(
        base_policy,
        target_enabled=True,
        environment=env,
        phase5_entry_signed=True,
    )
    enable_plan = plan_flag_transition(
        base_policy,
        enable=True,
        environment=env,
        phase5_entry_signed=True,
    )
    decision = persist_gray_decision_point(run_dir=run_dir, validator=validator, run_id=run_id)
    checks: list[dict[str, Any]] = []

    context = RuntimeContext(
        root=root,
        run_id=run_id,
        policy=base_policy,
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        run_dir_override=run_dir,
    )
    record_flag_transition(context, enable_plan, readiness=enable_readiness)

    probe_ok = False
    probe_error = ""
    if enable_plan.safe:
        try:
            probe = run_maintainer_real_disjoint_probe(
                root=root,
                run_dir=run_dir / "gray_probe",
                run_id=f"{run_id}-probe",
                validator=validator,
                policy=base_policy,
            )
            probe_ok = probe.audit.ok and probe.real_parallel
            checks.append({"name": "isolated_probe", "ok": probe_ok, "reason": probe.audit.summary})
        except Exception as exc:  # noqa: BLE001 — drill records failure
            probe_error = str(exc)
            checks.append({"name": "isolated_probe", "ok": False, "reason": probe_error})
    else:
        checks.append(
            {
                "name": "enable_readiness",
                "ok": False,
                "reason": "; ".join(enable_readiness.blockers),
            }
        )

    rollback_policy = with_feature_flag(base_policy, REAL_DISJOINT_WRITE_FLAG, enabled=False)
    rollback_readiness = evaluate_rollback_safety(rollback_policy, environment=env)
    rollback_plan = plan_flag_transition(
        rollback_policy,
        enable=False,
        environment=env,
        phase5_entry_signed=True,
    )
    record_flag_transition(context, rollback_plan, readiness=rollback_readiness)
    flag_off = not rollback_plan.to_enabled
    checks.append(
        {
            "name": "rollback_flag_off",
            "ok": flag_off and rollback_readiness.ready,
            "reason": "Flag returned to disabled after drill.",
        }
    )

    record = {
        "schema_version": "0.1.0",
        "record_id": f"swarm-gray-drill-{run_id}",
        "run_id": run_id,
        "decision_id": decision["decision_id"],
        "probe_ok": probe_ok,
        "rollback_ok": flag_off and rollback_readiness.ready,
        "created_at": now_iso(),
        "summary": "Gray rollback drill completed." if probe_ok else "Gray drill blocked or probe failed.",
    }
    JsonlStore(validator).append(run_dir / "swarm_gray_rollout_records.jsonl", record, "swarm_gray_rollout_record")

    resolved = {**decision, "status": "resolved", "selected_option_id": "rollback_now", "resolved_at": now_iso()}
    JsonlStore(validator).append(run_dir / "decisions.jsonl", resolved, "decision_point")

    ok = enable_plan.safe and probe_ok and rollback_readiness.ready and flag_off
    summary = (
        "Gray enable DecisionPoint + isolated probe + rollback drill passed."
        if ok
        else f"Gray drill blocked: {probe_error or 'readiness/probe/rollback failed'}."
    )
    return GrayRollbackDrillResult(
        ok=ok,
        enable_readiness=enable_readiness,
        rollback_readiness=rollback_readiness,
        enable_plan=enable_plan,
        rollback_plan=rollback_plan,
        decision_point=decision,
        probe_run_id=f"{run_id}-probe",
        probe_ok=probe_ok,
        checks=checks,
        summary=summary,
    )
