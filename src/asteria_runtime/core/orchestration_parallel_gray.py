"""Orchestration parallel gray readiness (S64) — bridges S63 eval + S32/S34 swarm gray."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.utils.time import now_iso

ORCHESTRATION_PARALLEL_DECISION_KIND = "orchestration_parallel_gray"
DEFAULT_SPAWN_EVIDENCE = Path(".asteria/verification/orchestration_spawn_real_20260607.json")
DEFAULT_ROUTE_EVIDENCE = Path(".asteria/verification/orchestration_route_real_20260607.json")

SPAWN_MIN_HIT_RATE = 0.9
SPAWN_MIN_CASES = 20
ROUTE_MIN_HIT_RATE = 0.85
ROUTE_MIN_CASES = 8


@dataclass(frozen=True)
class RolloutPrerequisite:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class OrchestrationParallelReadiness:
    ready_for_decision_point: bool
    ready_for_maintainer_probe: bool
    cli_parallel_writes_default: bool
    spawn_parallel_workers_catalog_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    spawn_evidence: dict[str, Any] | None = None
    route_evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_maintainer_probe": self.ready_for_maintainer_probe,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "spawn_parallel_workers_catalog_default": self.spawn_parallel_workers_catalog_default,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "spawn_evidence_summary": (self.spawn_evidence or {}).get("summary"),
            "route_evidence_summary": (self.route_evidence or {}).get("summary"),
        }


def load_eval_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def evaluate_orchestration_parallel_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    gray_drill_ok: bool | None = None,
) -> OrchestrationParallelReadiness:
    """Assess whether orchestration parallel gray may proceed (does not enable flags)."""
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    cli_parallel_default = bool(agent_loop.get("parallel_writes", False))

    spawn_path = spawn_evidence_path or (root / DEFAULT_SPAWN_EVIDENCE)
    route_path = route_evidence_path or (root / DEFAULT_ROUTE_EVIDENCE)
    spawn_report = load_eval_report(spawn_path)
    route_report = load_eval_report(route_path)

    prerequisites: list[RolloutPrerequisite] = []
    blockers: list[str] = []

    spawn_ok, spawn_detail = _eval_spawn_gate(spawn_report)
    prerequisites.append(RolloutPrerequisite("s63_spawn_real_eval", spawn_ok, spawn_detail))
    if not spawn_ok:
        blockers.append("s63_spawn_eval_missing_or_below_threshold")

    route_ok, route_detail = _eval_route_gate(route_report)
    prerequisites.append(RolloutPrerequisite("s62_route_real_eval", route_ok, route_detail))
    if not route_ok:
        blockers.append("s62_route_eval_missing_or_below_threshold")

    policy_doc_ok = (root / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md").exists()
    prerequisites.append(
        RolloutPrerequisite(
            "orchestration_policy_doc",
            policy_doc_ok,
            "ORCHESTRATION_DECISION_POLICY.md present."
            if policy_doc_ok
            else "Missing orchestration policy doc.",
        )
    )
    if not policy_doc_ok:
        blockers.append("policy_doc_missing")

    beta_safe = not cli_parallel_default
    prerequisites.append(
        RolloutPrerequisite(
            "cli_parallel_writes_default_off",
            beta_safe,
            "CLI parallel_writes default remains false (Beta safe)."
            if beta_safe
            else "parallel_writes must stay false until DecisionPoint approves probe.",
        )
    )
    if not beta_safe:
        blockers.append("parallel_writes_already_default_on")

    if gray_drill_ok is not None:
        prerequisites.append(
            RolloutPrerequisite(
                "s32_gray_rollback_drill",
                gray_drill_ok,
                "S32 gray rollback drill passed."
                if gray_drill_ok
                else "S32 gray rollback drill not recorded for this run.",
            )
        )
        if not gray_drill_ok:
            blockers.append("gray_drill_not_passed")

    ready_for_decision = not blockers and all(item.ok for item in prerequisites)
    probe_blockers = list(blockers)
    if gray_drill_ok is not True:
        probe_blockers.append("maintainer_probe_requires_s32_drill")
    ready_for_probe = ready_for_decision and gray_drill_ok is True and not probe_blockers

    return OrchestrationParallelReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_maintainer_probe=ready_for_probe,
        cli_parallel_writes_default=cli_parallel_default,
        spawn_parallel_workers_catalog_default=False,
        prerequisites=prerequisites,
        blockers=blockers,
        spawn_evidence=spawn_report,
        route_evidence=route_report,
    )


def build_orchestration_parallel_decision_point(
    *,
    run_id: str,
    readiness: OrchestrationParallelReadiness,
    sequence: int = 1,
) -> dict[str, Any]:
    """DecisionPoint for Wave 2 maintainer isolated parallel probe (does not auto-enable)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": f"decision-orchestration-parallel-{max(1, sequence):04d}",
        "status": "pending",
        "question": (
            "Proceed to Wave 2 maintainer isolated parallel_writes probe? "
            "Beta default remains session_agent; spawn_parallel_workers stays catalog-unavailable "
            "until strong route + merge evidence in isolated runs."
        ),
        "recommended_option_id": "wave2_maintainer_probe" if readiness.ready_for_maintainer_probe else "defer",
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave2_maintainer_probe",
                "label": "Run isolated maintainer parallel_writes probe",
                "tradeoff": "Reuses S32 rollback drill + dual_disjoint case; no Studio default change.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep parallel gray off",
                "tradeoff": "Continue session_agent + loop subagent only.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Record rollback / keep flags off",
                "tradeoff": "Explicit evidence that production parallel remains disabled.",
                "action": "cancel_scope",
            },
        ],
        "impact": {
            "scope": "high",
            "budget": "high",
            "risk": "high",
            "quality": "medium",
        },
        "selected_option_id": None,
        "created_at": now_iso(),
        "metadata": {
            "kind": ORCHESTRATION_PARALLEL_DECISION_KIND,
            "run_id": run_id,
            "wave": 2,
            "requires_strong_spawn_eval": True,
            "requires_s32_gray_drill": True,
            "cli_parallel_writes_unchanged": True,
            "spawn_parallel_workers_studio_default": False,
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def persist_orchestration_parallel_decision_point(
    *,
    agent_dir: Path,
    validator: Any,
    decision_point: dict[str, Any],
) -> Path:
    from asteria_runtime.storage.json_store import JsonStore

    path = agent_dir / "decisions" / f"{decision_point['decision_id']}.json"
    JsonStore(validator).write(path, decision_point, "decision_point")
    return path


def _eval_spawn_gate(report: dict[str, Any] | None) -> tuple[bool, str]:
    if report is None:
        return False, "Missing spawn real eval report."
    if report.get("mode") != "real" or report.get("ok") is not True:
        return False, "Spawn real eval report not ok or not real mode."
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    hit_rate = float(summary.get("hit_rate") or 0)
    case_count = int(summary.get("case_count") or 0)
    if hit_rate < SPAWN_MIN_HIT_RATE or case_count < SPAWN_MIN_CASES:
        return (
            False,
            f"Spawn hit_rate={hit_rate} case_count={case_count} "
            f"(need >={SPAWN_MIN_HIT_RATE}, n>={SPAWN_MIN_CASES}).",
        )
    return True, f"Spawn real eval ok: {hit_rate:.1%} over {case_count} cases."


def _eval_route_gate(report: dict[str, Any] | None) -> tuple[bool, str]:
    if report is None:
        return False, "Missing route real eval report."
    if report.get("mode") != "model" or report.get("ok") is not True:
        return False, "Route real eval report not ok or not model mode."
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    hit_rate = float(summary.get("hit_rate") or 0)
    case_count = int(summary.get("case_count") or 0)
    if hit_rate < ROUTE_MIN_HIT_RATE or case_count < ROUTE_MIN_CASES:
        return (
            False,
            f"Route hit_rate={hit_rate} case_count={case_count} "
            f"(need >={ROUTE_MIN_HIT_RATE}, n>={ROUTE_MIN_CASES}).",
        )
    return True, f"Route real eval ok: {hit_rate:.1%} over {case_count} cases."
