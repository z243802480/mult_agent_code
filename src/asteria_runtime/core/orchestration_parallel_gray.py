"""Orchestration parallel gray readiness (S64) — bridges S63 eval + S32/S34 swarm gray."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from asteria_runtime.utils.time import now_iso

if TYPE_CHECKING:
    from asteria_runtime.storage.schema_validator import SchemaValidator

ORCHESTRATION_PARALLEL_DECISION_KIND = "orchestration_parallel_gray"
DEFAULT_SPAWN_EVIDENCE = Path(".asteria/verification/orchestration_spawn_real_20260607.json")
DEFAULT_ROUTE_EVIDENCE = Path(".asteria/verification/orchestration_route_real_20260607.json")
DEFAULT_WAVE2_EVIDENCE = Path(".asteria/verification/orchestration_wave2_probe.json")
WAVE2_DECISION_ID = "decision-orchestration-parallel-0001"
WAVE3_DECISION_ID = "decision-orchestration-parallel-0002"
WAVE4_DECISION_ID = "decision-orchestration-parallel-0003"
CATALOG_GRAY_POLICY_KEY = "spawn_parallel_workers_catalog_gray"
WORKFLOWS_GRAY_POLICY_KEY = "orchestration_workflows_gray"
DEFAULT_WAVE3_EVIDENCE = Path(".asteria/verification/orchestration_wave3_catalog_probe.json")
DEFAULT_WAVE4_EVIDENCE = Path(".asteria/verification/orchestration_wave4_workflows_probe.json")
WAVE5_DECISION_ID = "decision-orchestration-parallel-0004"
WAVE6_DECISION_ID = "decision-orchestration-parallel-0005"
WAVE7_DECISION_ID = "decision-orchestration-parallel-0006"
PRODUCTION_PATH_POLICY_KEY = "isolated_parallel_write_production_path"
DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY = "orchestration_dynamic_workflows_gray"
LIVE_EXECUTION_GRAY_POLICY_KEY = "orchestration_dynamic_live_execution_gray"
MAX_PARALLEL_WORKERS_POLICY_KEY = "max_parallel_workers_per_run"
DEFAULT_WAVE5_EVIDENCE = Path(".asteria/verification/orchestration_wave5_production_path.json")
DEFAULT_WAVE6_EVIDENCE = Path(".asteria/verification/orchestration_wave6_dynamic_probe.json")
DEFAULT_WAVE7_EVIDENCE = Path(".asteria/verification/orchestration_wave7_live_probe.json")

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
    catalog_gray_default = bool(agent_loop.get(CATALOG_GRAY_POLICY_KEY, False))

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
        spawn_parallel_workers_catalog_default=catalog_gray_default,
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


def _resolve_wave3_gate_path(root: Path) -> Path:
    local = root / "benchmarks" / "orchestration_wave3_catalog_gate.json"
    if local.exists():
        return local
    repo_gate = Path.cwd() / "benchmarks" / "orchestration_wave3_catalog_gate.json"
    if repo_gate.exists():
        return repo_gate
    return local


def orchestration_parallel_decision_path(agent_dir: Path, decision_id: str) -> Path:
    return agent_dir / "decisions" / f"{decision_id}.json"


def resolve_orchestration_parallel_decision(
    *,
    agent_dir: Path,
    validator: Any,
    decision_id: str,
    selected_option_id: str,
) -> dict[str, Any]:
    from asteria_runtime.storage.json_store import JsonStore

    path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not path.exists():
        raise FileNotFoundError(f"Decision not found: {path}")
    store = JsonStore(validator)
    decision = store.read(path, "decision_point")
    if decision.get("status") == "resolved":
        if decision.get("selected_option_id") == selected_option_id:
            return decision
        raise ValueError(
            f"Decision already resolved with {decision.get('selected_option_id')}: {decision_id}"
        )
    if decision.get("status") != "pending":
        raise ValueError(f"Decision is not pending: {decision_id}")
    allowed = {str(item.get("option_id")) for item in (decision.get("options") or [])}
    if selected_option_id not in allowed:
        raise ValueError(f"Invalid option: {selected_option_id}")
    decision = {
        **decision,
        "status": "resolved",
        "selected_option_id": selected_option_id,
        "resolved_at": now_iso(),
    }
    validator.validate("decision_point", decision)
    store.write(path, decision, "decision_point")
    return decision


@dataclass(frozen=True)
class OrchestrationWave2BandResult:
    ok: bool
    isolated_workspace: Path
    decision: dict[str, Any]
    production_gray: Any
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        pg = self.production_gray
        return {
            "ok": self.ok,
            "isolated_workspace": str(self.isolated_workspace),
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "production_gray_ok": getattr(pg, "ok", False),
            "gray_drill_ok": getattr(pg, "gray_drill_ok", False),
            "execute_ok": getattr(getattr(pg, "execute", None), "ok", False),
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave2_band(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = "decision-orchestration-parallel-0001",
    selected_option_id: str = "wave2_maintainer_probe",
    isolated_workspace: Path | None = None,
) -> OrchestrationWave2BandResult:
    """Resolve Wave 2 DecisionPoint and run S34 production gray band in isolation."""
    import shutil
    import tempfile

    from asteria_runtime.core.swarm_production_gray import run_production_gray_band

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    readiness = evaluate_orchestration_parallel_readiness(
        root=repo_root,
        policy=None,
        gray_drill_ok=True,
    )
    if not readiness.ready_for_maintainer_probe:
        blockers = ", ".join(readiness.blockers) or "readiness failed"
        raise RuntimeError(f"Wave 2 not ready: {blockers}")

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    workspace = isolated_workspace
    cleanup = False
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="asteria-wave2-probe-"))
        cleanup = True
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        band = run_production_gray_band(workspace, validator)
        evidence_src = band.evidence_path
        verification_dir = agent_dir / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)
        evidence_dest = verification_dir / "orchestration_wave2_probe.json"
        if evidence_src and evidence_src.exists():
            payload = json.loads(evidence_src.read_text(encoding="utf-8"))
            payload["wave"] = 2
            payload["decision_id"] = decision_id
            payload["selected_option_id"] = selected_option_id
            payload["isolated_workspace"] = str(workspace)
            payload["orchestration_eval_refs"] = {
                "spawn": str(DEFAULT_SPAWN_EVIDENCE),
                "route": str(DEFAULT_ROUTE_EVIDENCE),
            }
            evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            evidence_dest = None

        ok = band.ok
        summary = (
            "Wave 2 isolated parallel_writes probe passed (dual_disjoint + gray rollback)."
            if ok
            else "Wave 2 probe failed; parallel_writes remains off."
        )
        return OrchestrationWave2BandResult(
            ok=ok,
            isolated_workspace=workspace,
            decision=decision,
            production_gray=band,
            evidence_path=evidence_dest,
            summary=summary,
        )
    finally:
        if cleanup and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)


@dataclass(frozen=True)
class Wave3CatalogReadiness:
    ready_for_decision_point: bool
    ready_for_catalog_probe: bool
    wave2_probe_ok: bool
    wave2_decision_ok: bool
    catalog_gray_enabled: bool
    cli_parallel_writes_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    base_readiness: OrchestrationParallelReadiness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_catalog_probe": self.ready_for_catalog_probe,
            "wave2_probe_ok": self.wave2_probe_ok,
            "wave2_decision_ok": self.wave2_decision_ok,
            "catalog_gray_enabled": self.catalog_gray_enabled,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "base_readiness": self.base_readiness.to_dict() if self.base_readiness else None,
        }


def load_wave2_decision(agent_dir: Path) -> dict[str, Any] | None:
    path = orchestration_parallel_decision_path(agent_dir, WAVE2_DECISION_ID)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def wave2_probe_passed(root: Path, *, wave2_evidence_path: Path | None = None) -> tuple[bool, str]:
    report = load_eval_report(wave2_evidence_path or (root / DEFAULT_WAVE2_EVIDENCE))
    if report is None:
        return False, "Missing Wave 2 probe evidence."
    if report.get("ok") is not True:
        return False, "Wave 2 probe evidence not ok."
    return True, "Wave 2 isolated probe passed."


def wave2_decision_resolved(agent_dir: Path) -> tuple[bool, str]:
    decision = load_wave2_decision(agent_dir)
    if decision is None:
        return False, f"Missing resolved Wave 2 decision: {WAVE2_DECISION_ID}."
    if decision.get("status") != "resolved":
        return False, f"Wave 2 decision not resolved: {WAVE2_DECISION_ID}."
    if decision.get("selected_option_id") != "wave2_maintainer_probe":
        return False, "Wave 2 decision did not select wave2_maintainer_probe."
    return True, "Wave 2 DecisionPoint resolved for maintainer probe."


def evaluate_wave3_catalog_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    wave2_evidence_path: Path | None = None,
) -> Wave3CatalogReadiness:
    """Assess Wave 3 catalog gray readiness (does not enable catalog gray)."""
    root = root.resolve()
    agent_dir = root / ".asteria"
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    catalog_gray_enabled = bool(agent_loop.get(CATALOG_GRAY_POLICY_KEY, False))
    cli_parallel_default = bool(agent_loop.get("parallel_writes", False))

    base = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        gray_drill_ok=True,
    )

    prerequisites: list[RolloutPrerequisite] = list(base.prerequisites)
    blockers = list(base.blockers)

    wave2_ok, wave2_detail = wave2_probe_passed(root, wave2_evidence_path=wave2_evidence_path)
    prerequisites.append(RolloutPrerequisite("wave2_isolated_probe", wave2_ok, wave2_detail))
    if not wave2_ok:
        blockers.append("wave2_probe_missing_or_failed")

    wave2_decision_ok, wave2_decision_detail = wave2_decision_resolved(agent_dir)
    prerequisites.append(
        RolloutPrerequisite("wave2_decision_resolved", wave2_decision_ok, wave2_decision_detail)
    )
    if not wave2_decision_ok:
        blockers.append("wave2_decision_not_resolved")

    catalog_off = not catalog_gray_enabled
    prerequisites.append(
        RolloutPrerequisite(
            "catalog_gray_still_off",
            catalog_off,
            "spawn_parallel_workers catalog gray remains disabled before Wave 3 probe."
            if catalog_off
            else "Catalog gray already enabled; probe is idempotent re-verify only.",
        )
    )

    ready_for_decision = not blockers and all(item.ok for item in prerequisites[:-1])
    probe_blockers = list(blockers)
    if cli_parallel_default:
        probe_blockers.append("cli_parallel_writes_must_stay_off")
    ready_for_probe = ready_for_decision and not cli_parallel_default

    return Wave3CatalogReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_catalog_probe=ready_for_probe,
        wave2_probe_ok=wave2_ok,
        wave2_decision_ok=wave2_decision_ok,
        catalog_gray_enabled=catalog_gray_enabled,
        cli_parallel_writes_default=cli_parallel_default,
        prerequisites=prerequisites,
        blockers=probe_blockers,
        base_readiness=base,
    )


def build_wave3_catalog_decision_point(
    *,
    run_id: str,
    readiness: Wave3CatalogReadiness,
) -> dict[str, Any]:
    """DecisionPoint for Wave 3 spawn_parallel_workers catalog gray (does not auto-enable)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": WAVE3_DECISION_ID,
        "status": "pending",
        "question": (
            "Enable spawn_parallel_workers catalog gray for maintainer Studio routing? "
            "CLI parallel_writes default stays false; strong route must still select this capability."
        ),
        "recommended_option_id": "wave3_catalog_gray" if readiness.ready_for_catalog_probe else "defer",
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave3_catalog_gray",
                "label": "Enable catalog gray for spawn_parallel_workers",
                "tradeoff": "Strong router may select parallel dispatch; execution still requires harness + merge gates.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep catalog unavailable",
                "tradeoff": "Continue session_agent ingress only.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Ensure catalog gray stays off",
                "tradeoff": "Explicit rollback of Wave 3 catalog exposure.",
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
            "wave": 3,
            "requires_wave2_probe": True,
            "requires_strong_route_selection": True,
            "cli_parallel_writes_unchanged": True,
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def set_spawn_parallel_workers_catalog_gray(
    *,
    agent_dir: Path,
    validator: Any,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle maintainer catalog gray without changing CLI parallel_writes default."""
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.json_store import JsonStore

    policy = load_policy_config(agent_dir, validator)
    agent_loop = dict(policy.get("agent_loop") or {})
    if bool(agent_loop.get("parallel_writes", False)):
        raise RuntimeError("Refusing catalog gray while agent_loop.parallel_writes is enabled.")
    agent_loop[CATALOG_GRAY_POLICY_KEY] = enabled
    policy = {**policy, "agent_loop": agent_loop}
    path = agent_dir / "policies.json"
    JsonStore(validator).write(path, policy, "policy_config")
    return policy


def verify_spawn_parallel_workers_catalog_state(
    root: Path,
    *,
    validator: Any,
    expect_available: bool,
) -> tuple[bool, str]:
    from asteria_runtime.core.runtime_orchestration_catalog import build_runtime_orchestration_catalog

    catalog = build_runtime_orchestration_catalog(root, validator=validator)
    spawn = catalog.get("spawn_parallel_workers")
    if spawn is None:
        return False, "spawn_parallel_workers missing from catalog."
    if spawn.available is expect_available:
        state = "available" if expect_available else "unavailable"
        return True, f"spawn_parallel_workers catalog is {state} as expected."
    return False, (
        f"spawn_parallel_workers availability mismatch: got {spawn.available}, "
        f"expected {expect_available}."
    )


def run_wave3_catalog_route_regression(
    root: Path,
    *,
    gate_path: Path | None = None,
) -> tuple[bool, list[dict[str, Any]], str]:
    """Rules-mode route cases must not regress to spawn_parallel_workers when catalog gray is on."""
    from asteria_runtime.route_worker import handle_route_request

    gate_file = gate_path or _resolve_wave3_gate_path(root)
    if not gate_file.exists():
        return False, [], f"Missing Wave 3 gate: {gate_file}"
    gate = json.loads(gate_file.read_text(encoding="utf-8"))
    cases = gate.get("route_regression_cases") or []
    results: list[dict[str, Any]] = []
    hits = 0
    for case in cases:
        response = handle_route_request(
            {
                "id": case.get("id"),
                "op": "route",
                "root": str(root),
                "message": case.get("message"),
                "mode": "auto",
                "rules_only": True,
                "router_mode": "rules",
                "include_catalog": False,
            }
        )
        capability_id = response.get("capability_id")
        forbidden = {str(item) for item in (case.get("forbidden_capabilities") or [])}
        accepted = {str(item) for item in (case.get("accept_capabilities") or [])}
        if not accepted and case.get("expect_capability"):
            accepted = {str(case.get("expect_capability"))}
        ok = response.get("ok") is True and capability_id not in forbidden
        if accepted:
            ok = ok and capability_id in accepted
        if ok:
            hits += 1
        results.append(
            {
                "id": case.get("id"),
                "ok": ok,
                "capability_id": capability_id,
                "expect_capability": case.get("expect_capability"),
                "forbidden_capabilities": sorted(forbidden),
            }
        )
    case_count = max(len(results), 1)
    hit_rate = hits / case_count
    min_rate = float((gate.get("thresholds") or {}).get("route_regression_min_hit_rate", 1.0))
    ok = hit_rate >= min_rate
    summary = f"Wave 3 route regression {hit_rate:.1%} over {len(results)} cases."
    return ok, results, summary


@dataclass(frozen=True)
class OrchestrationWave3CatalogResult:
    ok: bool
    decision: dict[str, Any]
    catalog_available: bool
    route_regression_ok: bool
    route_regression: list[dict[str, Any]]
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "catalog_available": self.catalog_available,
            "route_regression_ok": self.route_regression_ok,
            "route_regression": self.route_regression,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave3_catalog_probe(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = WAVE3_DECISION_ID,
    selected_option_id: str = "wave3_catalog_gray",
) -> OrchestrationWave3CatalogResult:
    """Resolve Wave 3 DecisionPoint and enable maintainer catalog gray."""
    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    policy = load_policy_config(agent_dir, validator)
    readiness = evaluate_wave3_catalog_readiness(root=repo_root, policy=policy)
    if not readiness.ready_for_catalog_probe and not readiness.catalog_gray_enabled:
        blockers = ", ".join(readiness.blockers) or "Wave 3 not ready"
        raise RuntimeError(f"Wave 3 catalog probe not ready: {blockers}")

    decision_path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not decision_path.exists():
        persist_orchestration_parallel_decision_point(
            agent_dir=agent_dir,
            validator=validator,
            decision_point=build_wave3_catalog_decision_point(
                run_id="orchestration-wave3-catalog-probe",
                readiness=readiness,
            ),
        )

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    set_spawn_parallel_workers_catalog_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    catalog_ok, catalog_detail = verify_spawn_parallel_workers_catalog_state(
        repo_root,
        validator=validator,
        expect_available=True,
    )
    route_ok, route_results, route_summary = run_wave3_catalog_route_regression(repo_root)

    ok = catalog_ok and route_ok
    verification_dir = agent_dir / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = verification_dir / "orchestration_wave3_catalog_probe.json"
    payload = {
        "schema_version": "0.1.0",
        "wave": 3,
        "ok": ok,
        "recorded_at": now_iso(),
        "decision_id": decision_id,
        "selected_option_id": selected_option_id,
        "catalog_gray_policy_key": CATALOG_GRAY_POLICY_KEY,
        "cli_parallel_writes_unchanged": not bool(
            (load_policy_config(agent_dir, validator).get("agent_loop") or {}).get("parallel_writes")
        ),
        "catalog_check": {"ok": catalog_ok, "detail": catalog_detail},
        "route_regression_ok": route_ok,
        "route_regression_summary": route_summary,
        "route_regression": route_results,
        "wave2_evidence_ref": str(DEFAULT_WAVE2_EVIDENCE),
        "orchestration_eval_refs": {
            "spawn": str(DEFAULT_SPAWN_EVIDENCE),
            "route": str(DEFAULT_ROUTE_EVIDENCE),
        },
    }
    evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        "Wave 3 spawn_parallel_workers catalog gray enabled; route regression passed."
        if ok
        else "Wave 3 catalog probe failed; review evidence before Studio exposure."
    )
    return OrchestrationWave3CatalogResult(
        ok=ok,
        decision=decision,
        catalog_available=catalog_ok,
        route_regression_ok=route_ok,
        route_regression=route_results,
        evidence_path=evidence_dest,
        summary=summary,
    )


def _resolve_wave4_gate_path(root: Path) -> Path:
    local = root / "benchmarks" / "orchestration_wave4_workflows_gate.json"
    if local.exists():
        return local
    repo_gate = Path.cwd() / "benchmarks" / "orchestration_wave4_workflows_gate.json"
    if repo_gate.exists():
        return repo_gate
    return local


def load_wave3_decision(agent_dir: Path) -> dict[str, Any] | None:
    path = orchestration_parallel_decision_path(agent_dir, WAVE3_DECISION_ID)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def wave3_probe_passed(root: Path, *, wave3_evidence_path: Path | None = None) -> tuple[bool, str]:
    report = load_eval_report(wave3_evidence_path or (root / DEFAULT_WAVE3_EVIDENCE))
    if report is None:
        return False, "Missing Wave 3 catalog probe evidence."
    if report.get("ok") is not True:
        return False, "Wave 3 catalog probe evidence not ok."
    return True, "Wave 3 catalog gray probe passed."


def wave3_decision_resolved(agent_dir: Path) -> tuple[bool, str]:
    decision = load_wave3_decision(agent_dir)
    if decision is None:
        return False, f"Missing resolved Wave 3 decision: {WAVE3_DECISION_ID}."
    if decision.get("status") != "resolved":
        return False, f"Wave 3 decision not resolved: {WAVE3_DECISION_ID}."
    if decision.get("selected_option_id") != "wave3_catalog_gray":
        return False, "Wave 3 decision did not select wave3_catalog_gray."
    return True, "Wave 3 DecisionPoint resolved for catalog gray."


@dataclass(frozen=True)
class Wave4WorkflowsReadiness:
    ready_for_decision_point: bool
    ready_for_workflows_probe: bool
    wave3_probe_ok: bool
    wave3_decision_ok: bool
    catalog_gray_enabled: bool
    workflows_gray_enabled: bool
    cli_parallel_writes_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    wave3_readiness: Wave3CatalogReadiness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_workflows_probe": self.ready_for_workflows_probe,
            "wave3_probe_ok": self.wave3_probe_ok,
            "wave3_decision_ok": self.wave3_decision_ok,
            "catalog_gray_enabled": self.catalog_gray_enabled,
            "workflows_gray_enabled": self.workflows_gray_enabled,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "wave3_readiness": self.wave3_readiness.to_dict() if self.wave3_readiness else None,
        }


def evaluate_wave4_workflows_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    wave2_evidence_path: Path | None = None,
    wave3_evidence_path: Path | None = None,
) -> Wave4WorkflowsReadiness:
    """Assess Wave 4 workflows gray readiness (does not enable workflows gray)."""
    root = root.resolve()
    agent_dir = root / ".asteria"
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    catalog_gray_enabled = bool(agent_loop.get(CATALOG_GRAY_POLICY_KEY, False))
    workflows_gray_enabled = bool(agent_loop.get(WORKFLOWS_GRAY_POLICY_KEY, False))
    cli_parallel_default = bool(agent_loop.get("parallel_writes", False))

    wave3 = evaluate_wave3_catalog_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        wave2_evidence_path=wave2_evidence_path,
    )

    base = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        gray_drill_ok=True,
    )
    prerequisites: list[RolloutPrerequisite] = list(base.prerequisites)
    blockers = list(base.blockers)

    wave3_ok, wave3_detail = wave3_probe_passed(root, wave3_evidence_path=wave3_evidence_path)
    prerequisites.append(RolloutPrerequisite("wave3_catalog_probe", wave3_ok, wave3_detail))
    if not wave3_ok:
        blockers.append("wave3_probe_missing_or_failed")

    wave3_decision_ok, wave3_decision_detail = wave3_decision_resolved(agent_dir)
    prerequisites.append(
        RolloutPrerequisite("wave3_decision_resolved", wave3_decision_ok, wave3_decision_detail)
    )
    if not wave3_decision_ok:
        blockers.append("wave3_decision_not_resolved")

    catalog_on = catalog_gray_enabled
    prerequisites.append(
        RolloutPrerequisite(
            "catalog_gray_enabled",
            catalog_on,
            "spawn_parallel_workers catalog gray is enabled."
            if catalog_on
            else "Wave 4 requires Wave 3 catalog gray on maintainer workspace.",
        )
    )
    if not catalog_on:
        blockers.append("catalog_gray_not_enabled")

    workflows_off = not workflows_gray_enabled
    prerequisites.append(
        RolloutPrerequisite(
            "workflows_gray_still_off",
            workflows_off,
            "orchestration_workflows_gray remains disabled before Wave 4 probe."
            if workflows_off
            else "Workflows gray already enabled; probe is idempotent re-verify only.",
        )
    )

    ready_for_decision = not blockers and all(item.ok for item in prerequisites[:-1])
    probe_blockers = list(blockers)
    if cli_parallel_default:
        probe_blockers.append("cli_parallel_writes_must_stay_off")
    ready_for_probe = ready_for_decision and not cli_parallel_default

    return Wave4WorkflowsReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_workflows_probe=ready_for_probe,
        wave3_probe_ok=wave3_ok,
        wave3_decision_ok=wave3_decision_ok,
        catalog_gray_enabled=catalog_gray_enabled,
        workflows_gray_enabled=workflows_gray_enabled,
        cli_parallel_writes_default=cli_parallel_default,
        prerequisites=prerequisites,
        blockers=probe_blockers,
        wave3_readiness=wave3,
    )


def build_wave4_workflows_decision_point(
    *,
    run_id: str,
    readiness: Wave4WorkflowsReadiness,
) -> dict[str, Any]:
    """DecisionPoint for Wave 4 workflows gray (does not enable CLI parallel_writes default)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": WAVE4_DECISION_ID,
        "status": "pending",
        "question": (
            "Enable orchestration workflows gray after isolated real_disjoint probe? "
            "CLI parallel_writes default stays false; real_disjoint_write_workers default stays false."
        ),
        "recommended_option_id": "wave4_workflows_gray" if readiness.ready_for_workflows_probe else "defer",
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave4_workflows_gray",
                "label": "Enable maintainer workflows gray",
                "tradeoff": "Allows CC workflows-scale maintainer orchestration; not Beta CLI default.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep workflows gray off",
                "tradeoff": "Stop at Wave 3 catalog gray.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Rollback workflows/catalog gray flags",
                "tradeoff": "Explicit rollback to session_agent ingress only.",
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
            "wave": 4,
            "requires_wave3_catalog_gray": True,
            "requires_real_disjoint_probe": True,
            "cli_parallel_writes_unchanged": True,
            "real_disjoint_default_unchanged": True,
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def set_orchestration_workflows_gray(
    *,
    agent_dir: Path,
    validator: Any,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle maintainer workflows gray without enabling CLI parallel_writes or real_disjoint default."""
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.json_store import JsonStore

    policy = load_policy_config(agent_dir, validator)
    agent_loop = dict(policy.get("agent_loop") or {})
    if bool(agent_loop.get("parallel_writes", False)):
        raise RuntimeError("Refusing workflows gray while agent_loop.parallel_writes is enabled.")
    agent_loop[WORKFLOWS_GRAY_POLICY_KEY] = enabled
    policy = {**policy, "agent_loop": agent_loop}
    path = agent_dir / "policies.json"
    JsonStore(validator).write(path, policy, "policy_config")
    return policy


def run_wave4_isolated_real_disjoint_probe(
    workspace: Path,
    validator: Any,
) -> Any:
    """Run S23 real_disjoint probe in an isolated workspace (temp dir)."""
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.swarm_pipeline import run_maintainer_real_disjoint_probe

    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    InitCommand(workspace).run()
    default_policy = json.loads(
        (Path(__file__).resolve().parents[1] / "templates" / "policies.default.json").read_text(
            encoding="utf-8"
        )
    )
    run_id = "run-wave4-workflows-probe"
    run_dir = workspace / ".asteria" / "runs" / run_id
    return run_maintainer_real_disjoint_probe(
        root=workspace,
        run_dir=run_dir,
        run_id=run_id,
        validator=validator,
        policy=default_policy,
    )


def run_wave4_workflows_route_regression(
    root: Path,
    *,
    gate_path: Path | None = None,
) -> tuple[bool, list[dict[str, Any]], str]:
    """Rules-mode regression when catalog gray is on (small edits must not pick parallel)."""
    from asteria_runtime.route_worker import handle_route_request

    gate_file = gate_path or _resolve_wave4_gate_path(root)
    if not gate_file.exists():
        return False, [], f"Missing Wave 4 gate: {gate_file}"
    gate = json.loads(gate_file.read_text(encoding="utf-8"))
    cases = gate.get("route_regression_cases") or []
    results: list[dict[str, Any]] = []
    hits = 0
    for case in cases:
        response = handle_route_request(
            {
                "id": case.get("id"),
                "op": "route",
                "root": str(root),
                "message": case.get("message"),
                "mode": "auto",
                "rules_only": True,
                "router_mode": "rules",
                "include_catalog": False,
            }
        )
        capability_id = response.get("capability_id")
        forbidden = {str(item) for item in (case.get("forbidden_capabilities") or [])}
        accepted = {str(item) for item in (case.get("accept_capabilities") or [])}
        if not accepted and case.get("expect_capability"):
            accepted = {str(case.get("expect_capability"))}
        ok = response.get("ok") is True and capability_id not in forbidden
        if accepted:
            ok = ok and capability_id in accepted
        if ok:
            hits += 1
        results.append(
            {
                "id": case.get("id"),
                "ok": ok,
                "capability_id": capability_id,
                "expect_capability": case.get("expect_capability"),
                "forbidden_capabilities": sorted(forbidden),
            }
        )
    case_count = max(len(results), 1)
    hit_rate = hits / case_count
    min_rate = float((gate.get("thresholds") or {}).get("route_regression_min_hit_rate", 1.0))
    ok = hit_rate >= min_rate
    summary = f"Wave 4 route regression {hit_rate:.1%} over {len(results)} cases."
    return ok, results, summary


@dataclass(frozen=True)
class OrchestrationWave4WorkflowsResult:
    ok: bool
    decision: dict[str, Any]
    real_disjoint_ok: bool
    real_disjoint: Any
    route_regression_ok: bool
    route_regression: list[dict[str, Any]]
    isolated_workspace: Path
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        rd = self.real_disjoint
        return {
            "ok": self.ok,
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "real_disjoint_ok": self.real_disjoint_ok,
            "real_disjoint_summary": getattr(rd, "audit", None) and getattr(rd.audit, "ok", None),
            "route_regression_ok": self.route_regression_ok,
            "route_regression": self.route_regression,
            "isolated_workspace": str(self.isolated_workspace),
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave4_workflows_probe(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = WAVE4_DECISION_ID,
    selected_option_id: str = "wave4_workflows_gray",
    isolated_workspace: Path | None = None,
) -> OrchestrationWave4WorkflowsResult:
    """Resolve Wave 4 DecisionPoint, run isolated real_disjoint probe, enable workflows gray."""
    import shutil
    import tempfile

    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    policy = load_policy_config(agent_dir, validator)
    readiness = evaluate_wave4_workflows_readiness(root=repo_root, policy=policy)
    if not readiness.ready_for_workflows_probe and not readiness.workflows_gray_enabled:
        blockers = ", ".join(readiness.blockers) or "Wave 4 not ready"
        raise RuntimeError(f"Wave 4 workflows probe not ready: {blockers}")

    decision_path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not decision_path.exists():
        persist_orchestration_parallel_decision_point(
            agent_dir=agent_dir,
            validator=validator,
            decision_point=build_wave4_workflows_decision_point(
                run_id="orchestration-wave4-workflows-probe",
                readiness=readiness,
            ),
        )

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    workspace = isolated_workspace
    cleanup = False
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="asteria-wave4-probe-"))
        cleanup = True
    workspace = workspace.resolve()

    real_disjoint_result = None
    real_disjoint_ok = False
    try:
        real_disjoint_result = run_wave4_isolated_real_disjoint_probe(workspace, validator)
        real_disjoint_ok = bool(real_disjoint_result.real_parallel and real_disjoint_result.audit.ok)
    finally:
        if cleanup and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    set_orchestration_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    route_ok, route_results, route_summary = run_wave4_workflows_route_regression(repo_root)

    ok = real_disjoint_ok and route_ok
    verification_dir = agent_dir / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = verification_dir / "orchestration_wave4_workflows_probe.json"
    payload = {
        "schema_version": "0.1.0",
        "wave": 4,
        "ok": ok,
        "recorded_at": now_iso(),
        "decision_id": decision_id,
        "selected_option_id": selected_option_id,
        "workflows_gray_policy_key": WORKFLOWS_GRAY_POLICY_KEY,
        "cli_parallel_writes_unchanged": not bool(
            (load_policy_config(agent_dir, validator).get("agent_loop") or {}).get("parallel_writes")
        ),
        "real_disjoint_default_unchanged": not bool(
            (load_policy_config(agent_dir, validator).get("feature_flags") or {}).get(
                "real_disjoint_write_workers", {}
            ).get("enabled")
            if isinstance((load_policy_config(agent_dir, validator).get("feature_flags") or {}), dict)
            else False
        ),
        "real_disjoint_probe_ok": real_disjoint_ok,
        "real_disjoint_probe": real_disjoint_result.to_dict() if real_disjoint_result else None,
        "route_regression_ok": route_ok,
        "route_regression_summary": route_summary,
        "route_regression": route_results,
        "wave3_evidence_ref": str(DEFAULT_WAVE3_EVIDENCE),
        "isolated_workspace": str(workspace),
    }
    evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        "Wave 4 orchestration workflows gray enabled; real_disjoint isolated probe passed."
        if ok
        else "Wave 4 workflows probe failed; review evidence."
    )
    return OrchestrationWave4WorkflowsResult(
        ok=ok,
        decision=decision,
        real_disjoint_ok=real_disjoint_ok,
        real_disjoint=real_disjoint_result,
        route_regression_ok=route_ok,
        route_regression=route_results,
        isolated_workspace=workspace,
        evidence_path=evidence_dest,
        summary=summary,
    )


def _real_disjoint_feature_default_off(policy: dict[str, Any]) -> bool:
    flags = policy.get("feature_flags") if isinstance(policy.get("feature_flags"), dict) else {}
    entry = flags.get("real_disjoint_write_workers") if isinstance(flags, dict) else {}
    if not isinstance(entry, dict):
        return True
    return not bool(entry.get("enabled"))


def load_wave4_decision(agent_dir: Path) -> dict[str, Any] | None:
    path = orchestration_parallel_decision_path(agent_dir, WAVE4_DECISION_ID)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def wave4_probe_passed(root: Path, *, wave4_evidence_path: Path | None = None) -> tuple[bool, str]:
    report = load_eval_report(wave4_evidence_path or (root / DEFAULT_WAVE4_EVIDENCE))
    if report is None:
        return False, "Missing Wave 4 workflows probe evidence."
    if report.get("ok") is not True:
        return False, "Wave 4 workflows probe evidence not ok."
    return True, "Wave 4 L2 qualification probe passed."


def wave4_decision_resolved(agent_dir: Path) -> tuple[bool, str]:
    decision = load_wave4_decision(agent_dir)
    if decision is None:
        return False, f"Missing resolved Wave 4 decision: {WAVE4_DECISION_ID}."
    if decision.get("status") != "resolved":
        return False, f"Wave 4 decision not resolved: {WAVE4_DECISION_ID}."
    if decision.get("selected_option_id") != "wave4_workflows_gray":
        return False, "Wave 4 decision did not select wave4_workflows_gray."
    return True, "Wave 4 DecisionPoint resolved for L2 qualification."


@dataclass(frozen=True)
class Wave5ProductionPathReadiness:
    ready_for_decision_point: bool
    ready_for_production_probe: bool
    wave4_probe_ok: bool
    wave4_decision_ok: bool
    workflows_gray_enabled: bool
    catalog_gray_enabled: bool
    production_path_enabled: bool
    cli_parallel_writes_default: bool
    real_disjoint_default_off: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    wave4_readiness: Wave4WorkflowsReadiness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_production_probe": self.ready_for_production_probe,
            "wave4_probe_ok": self.wave4_probe_ok,
            "wave4_decision_ok": self.wave4_decision_ok,
            "workflows_gray_enabled": self.workflows_gray_enabled,
            "catalog_gray_enabled": self.catalog_gray_enabled,
            "production_path_enabled": self.production_path_enabled,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "real_disjoint_default_off": self.real_disjoint_default_off,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "wave4_readiness": self.wave4_readiness.to_dict() if self.wave4_readiness else None,
        }


def evaluate_wave5_production_path_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    wave2_evidence_path: Path | None = None,
    wave3_evidence_path: Path | None = None,
    wave4_evidence_path: Path | None = None,
    wave5_evidence_path: Path | None = None,
) -> Wave5ProductionPathReadiness:
    """Assess Wave 5 L2 production path readiness (does not enable production path)."""
    root = root.resolve()
    agent_dir = root / ".asteria"
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    catalog_gray = bool(agent_loop.get(CATALOG_GRAY_POLICY_KEY, False))
    workflows_gray = bool(agent_loop.get(WORKFLOWS_GRAY_POLICY_KEY, False))
    production_path = bool(agent_loop.get(PRODUCTION_PATH_POLICY_KEY, False))
    cli_parallel = bool(agent_loop.get("parallel_writes", False))
    real_disjoint_off = _real_disjoint_feature_default_off(policy)

    wave4 = evaluate_wave4_workflows_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        wave2_evidence_path=wave2_evidence_path,
        wave3_evidence_path=wave3_evidence_path,
    )

    base = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        gray_drill_ok=True,
    )
    prerequisites: list[RolloutPrerequisite] = list(base.prerequisites)
    blockers = list(wave4.blockers)

    wave4_ok, wave4_detail = wave4_probe_passed(root, wave4_evidence_path=wave4_evidence_path)
    prerequisites.append(RolloutPrerequisite("wave4_workflows_probe", wave4_ok, wave4_detail))
    if not wave4_ok:
        blockers.append("wave4_probe_missing_or_failed")

    wave4_decision_ok, wave4_decision_detail = wave4_decision_resolved(agent_dir)
    prerequisites.append(
        RolloutPrerequisite("wave4_decision_resolved", wave4_decision_ok, wave4_decision_detail)
    )
    if not wave4_decision_ok:
        blockers.append("wave4_decision_not_resolved")

    prerequisites.append(
        RolloutPrerequisite(
            "workflows_gray_enabled",
            workflows_gray,
            "orchestration_workflows_gray is enabled."
            if workflows_gray
            else "Wave 5 requires Wave 4 workflows gray.",
        )
    )
    if not workflows_gray:
        blockers.append("workflows_gray_not_enabled")

    prerequisites.append(
        RolloutPrerequisite(
            "catalog_gray_enabled",
            catalog_gray,
            "spawn_parallel_workers catalog gray is enabled."
            if catalog_gray
            else "Wave 5 requires Wave 3 catalog gray.",
        )
    )
    if not catalog_gray:
        blockers.append("catalog_gray_not_enabled")

    prerequisites.append(
        RolloutPrerequisite(
            "real_disjoint_default_off",
            real_disjoint_off,
            "real_disjoint_write_workers feature flag remains disabled by default."
            if real_disjoint_off
            else "Global real_disjoint_write_workers must stay off for Wave 5.",
        )
    )
    if not real_disjoint_off:
        blockers.append("real_disjoint_default_on")

    path_off = not production_path
    prerequisites.append(
        RolloutPrerequisite(
            "production_path_still_off",
            path_off,
            "isolated_parallel_write_production_path remains disabled before Wave 5 probe."
            if path_off
            else "Production path already enabled; probe is idempotent re-verify only.",
        )
    )

    ready_for_decision = not blockers and all(item.ok for item in prerequisites[:-1])
    probe_blockers = list(blockers)
    if cli_parallel:
        probe_blockers.append("cli_parallel_writes_must_stay_off")
    ready_for_probe = ready_for_decision and not cli_parallel

    return Wave5ProductionPathReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_production_probe=ready_for_probe,
        wave4_probe_ok=wave4_ok,
        wave4_decision_ok=wave4_decision_ok,
        workflows_gray_enabled=workflows_gray,
        catalog_gray_enabled=catalog_gray,
        production_path_enabled=production_path,
        cli_parallel_writes_default=cli_parallel,
        real_disjoint_default_off=real_disjoint_off,
        prerequisites=prerequisites,
        blockers=probe_blockers,
        wave4_readiness=wave4,
    )


def build_wave5_production_path_decision_point(
    *,
    run_id: str,
    readiness: Wave5ProductionPathReadiness,
) -> dict[str, Any]:
    """DecisionPoint for Wave 5 L2 isolated production path (explicit trigger; defaults unchanged)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": WAVE5_DECISION_ID,
        "status": "pending",
        "question": (
            "Enable isolated parallel write production path on this repository? "
            "Requires explicit --parallel-disjoint-writes or maintainer validation-run; "
            "CLI parallel_writes default stays false."
        ),
        "recommended_option_id": (
            "wave5_isolated_production_path" if readiness.ready_for_production_probe else "defer"
        ),
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave5_isolated_production_path",
                "label": "Enable L2 isolated production path (maintainer explicit)",
                "tradeoff": "Candidate workspace + merge gate validated on repo; not Beta default parallel.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep production path off",
                "tradeoff": "Stop at Wave 4 L2 qualification.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Rollback gray flags",
                "tradeoff": "Disable catalog/workflows/production path flags.",
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
            "wave": 5,
            "layer": "L2_isolated_parallel_write",
            "requires_wave4_workflows_gray": True,
            "requires_candidate_isolation": True,
            "cli_parallel_writes_unchanged": True,
            "real_disjoint_default_unchanged": True,
            "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def set_isolated_parallel_write_production_path(
    *,
    agent_dir: Path,
    validator: Any,
    enabled: bool,
) -> dict[str, Any]:
    """Enable maintainer L2 production path without changing CLI or feature-flag defaults."""
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.json_store import JsonStore

    policy = load_policy_config(agent_dir, validator)
    agent_loop = dict(policy.get("agent_loop") or {})
    if bool(agent_loop.get("parallel_writes", False)):
        raise RuntimeError("Refusing production path while agent_loop.parallel_writes is enabled.")
    agent_loop[PRODUCTION_PATH_POLICY_KEY] = enabled
    policy = {**policy, "agent_loop": agent_loop}
    path = agent_dir / "policies.json"
    JsonStore(validator).write(path, policy, "policy_config")
    return policy


def run_wave5_repo_production_path_band(
    repo_root: Path,
    validator: Any,
) -> dict[str, Any]:
    """Run L2 band on repository: real_disjoint (candidate) + explicit dual_disjoint execute."""
    from asteria_runtime.core.swarm_pipeline import run_maintainer_real_disjoint_probe
    from asteria_runtime.core.swarm_production_gray import run_dual_disjoint_execute_scenario

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    default_policy = json.loads(
        (Path(__file__).resolve().parents[1] / "templates" / "policies.default.json").read_text(
            encoding="utf-8"
        )
    )

    disjoint_run_id = f"run-wave5-production-disjoint-{now_iso().replace(':', '').replace('+', '')[:15]}"
    disjoint_run_dir = agent_dir / "runs" / disjoint_run_id
    disjoint = run_maintainer_real_disjoint_probe(
        root=repo_root,
        run_dir=disjoint_run_dir,
        run_id=disjoint_run_id,
        validator=validator,
        policy=default_policy,
    )

    execute = run_dual_disjoint_execute_scenario(repo_root, validator)

    disjoint_ok = bool(disjoint.real_parallel and disjoint.audit.ok)
    execute_ok = bool(execute.ok)
    ok = disjoint_ok and execute_ok

    return {
        "ok": ok,
        "isolation_model": "candidate_workspace + explicit parallel_writes execute",
        "real_disjoint_probe": disjoint.to_dict(),
        "dual_disjoint_execute": execute.to_dict(),
        "disjoint_run_dir": str(disjoint_run_dir),
        "execute_run_dir": str(execute.run_dir),
        "summary": (
            "Wave 5 L2 production path band passed (candidate + explicit execute)."
            if ok
            else "Wave 5 production path band failed."
        ),
    }


def persist_wave5_validation_run(
    *,
    agent_dir: Path,
    band: dict[str, Any],
) -> Path:
    """Write maintainer validation-run style evidence under .asteria/validation_runs/."""
    run_id = f"validation-wave5-isolated-parallel-{now_iso().replace(':', '').replace('+', '')[:15]}"
    run_dir = agent_dir / "validation_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    payload = {
        "schema_version": "0.1.0",
        "validation_run_id": run_id,
        "purpose": "Wave 5 L2 isolated parallel write production path",
        "status": "completed" if band.get("ok") else "failed",
        "recorded_at": now_iso(),
        "wave": 5,
        "layer": "L2",
        "defaults_unchanged": {
            "cli_parallel_writes": False,
            "real_disjoint_write_workers": False,
        },
        "band": band,
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


@dataclass(frozen=True)
class OrchestrationWave5ProductionResult:
    ok: bool
    decision: dict[str, Any]
    band: dict[str, Any]
    validation_run_path: Path | None
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "band_ok": self.band.get("ok"),
            "validation_run_path": str(self.validation_run_path) if self.validation_run_path else None,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave5_production_path_probe(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = WAVE5_DECISION_ID,
    selected_option_id: str = "wave5_isolated_production_path",
) -> OrchestrationWave5ProductionResult:
    """Resolve Wave 5 DecisionPoint and validate L2 production path on this repository."""
    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    policy = load_policy_config(agent_dir, validator)
    readiness = evaluate_wave5_production_path_readiness(root=repo_root, policy=policy)
    if not readiness.ready_for_production_probe and not readiness.production_path_enabled:
        blockers = ", ".join(readiness.blockers) or "Wave 5 not ready"
        raise RuntimeError(f"Wave 5 production path probe not ready: {blockers}")

    decision_path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not decision_path.exists():
        persist_orchestration_parallel_decision_point(
            agent_dir=agent_dir,
            validator=validator,
            decision_point=build_wave5_production_path_decision_point(
                run_id="orchestration-wave5-production-probe",
                readiness=readiness,
            ),
        )

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    band = run_wave5_repo_production_path_band(repo_root, validator)
    validation_path = persist_wave5_validation_run(agent_dir=agent_dir, band=band)

    set_isolated_parallel_write_production_path(agent_dir=agent_dir, validator=validator, enabled=True)

    policy_after = load_policy_config(agent_dir, validator)
    agent_loop = policy_after.get("agent_loop") or {}
    defaults_ok = (
        not bool(agent_loop.get("parallel_writes"))
        and _real_disjoint_feature_default_off(policy_after)
    )
    ok = bool(band.get("ok")) and defaults_ok

    verification_dir = agent_dir / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = verification_dir / "orchestration_wave5_production_path.json"
    payload = {
        "schema_version": "0.1.0",
        "wave": 5,
        "layer": "L2_isolated_parallel_write",
        "ok": ok,
        "recorded_at": now_iso(),
        "decision_id": decision_id,
        "selected_option_id": selected_option_id,
        "production_path_policy_key": PRODUCTION_PATH_POLICY_KEY,
        "cli_parallel_writes_unchanged": not bool(agent_loop.get("parallel_writes")),
        "real_disjoint_default_unchanged": _real_disjoint_feature_default_off(policy_after),
        "band": band,
        "validation_run_path": str(validation_path),
        "wave4_evidence_ref": str(DEFAULT_WAVE4_EVIDENCE),
        "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
        "explicit_trigger_note": "Use --parallel-disjoint-writes or maintainer validation-run; not CLI default.",
    }
    evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        "Wave 5 L2 isolated parallel write production path enabled; defaults unchanged."
        if ok
        else "Wave 5 production path probe failed; review validation_run evidence."
    )
    return OrchestrationWave5ProductionResult(
        ok=ok,
        decision=decision,
        band=band,
        validation_run_path=validation_path,
        evidence_path=evidence_dest,
        summary=summary,
    )


def _resolve_wave6_gate_path(root: Path) -> Path:
    local = root / "benchmarks" / "orchestration_wave6_dynamic_gate.json"
    if local.exists():
        return local
    repo_gate = Path.cwd() / "benchmarks" / "orchestration_wave6_dynamic_gate.json"
    if repo_gate.exists():
        return repo_gate
    return local


def load_wave5_decision(agent_dir: Path) -> dict[str, Any] | None:
    path = orchestration_parallel_decision_path(agent_dir, WAVE5_DECISION_ID)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def wave5_probe_passed(root: Path, *, wave5_evidence_path: Path | None = None) -> tuple[bool, str]:
    report = load_eval_report(wave5_evidence_path or (root / DEFAULT_WAVE5_EVIDENCE))
    if report is None:
        return False, "Missing Wave 5 production path probe evidence."
    if report.get("ok") is not True:
        return False, "Wave 5 production path probe evidence not ok."
    return True, "Wave 5 L2 production path probe passed."


def wave5_decision_resolved(agent_dir: Path) -> tuple[bool, str]:
    decision = load_wave5_decision(agent_dir)
    if decision is None:
        return False, f"Missing resolved Wave 5 decision: {WAVE5_DECISION_ID}."
    if decision.get("status") != "resolved":
        return False, f"Wave 5 decision not resolved: {WAVE5_DECISION_ID}."
    if decision.get("selected_option_id") != "wave5_isolated_production_path":
        return False, "Wave 5 decision did not select wave5_isolated_production_path."
    return True, "Wave 5 DecisionPoint resolved for L2 production path."


@dataclass(frozen=True)
class Wave6DynamicReadiness:
    ready_for_decision_point: bool
    ready_for_dynamic_probe: bool
    wave5_probe_ok: bool
    wave5_decision_ok: bool
    production_path_enabled: bool
    dynamic_gray_enabled: bool
    cli_parallel_writes_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    wave5_readiness: Wave5ProductionPathReadiness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_dynamic_probe": self.ready_for_dynamic_probe,
            "wave5_probe_ok": self.wave5_probe_ok,
            "wave5_decision_ok": self.wave5_decision_ok,
            "production_path_enabled": self.production_path_enabled,
            "dynamic_gray_enabled": self.dynamic_gray_enabled,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "wave5_readiness": self.wave5_readiness.to_dict() if self.wave5_readiness else None,
        }


def evaluate_wave6_dynamic_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    wave2_evidence_path: Path | None = None,
    wave3_evidence_path: Path | None = None,
    wave4_evidence_path: Path | None = None,
    wave5_evidence_path: Path | None = None,
) -> Wave6DynamicReadiness:
    """Assess Wave 6 L3 dynamic workflows readiness (does not enable dynamic gray)."""
    root = root.resolve()
    agent_dir = root / ".asteria"
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    production_path = bool(agent_loop.get(PRODUCTION_PATH_POLICY_KEY, False))
    dynamic_gray = bool(agent_loop.get(DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY, False))
    cli_parallel = bool(agent_loop.get("parallel_writes", False))

    wave5 = evaluate_wave5_production_path_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        wave2_evidence_path=wave2_evidence_path,
        wave3_evidence_path=wave3_evidence_path,
        wave4_evidence_path=wave4_evidence_path,
        wave5_evidence_path=wave5_evidence_path,
    )

    base = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        gray_drill_ok=True,
    )
    prerequisites: list[RolloutPrerequisite] = list(base.prerequisites)
    blockers = list(wave5.blockers)

    wave5_ok, wave5_detail = wave5_probe_passed(root, wave5_evidence_path=wave5_evidence_path)
    prerequisites.append(RolloutPrerequisite("wave5_production_probe", wave5_ok, wave5_detail))
    if not wave5_ok:
        blockers.append("wave5_probe_missing_or_failed")

    wave5_decision_ok, wave5_decision_detail = wave5_decision_resolved(agent_dir)
    prerequisites.append(
        RolloutPrerequisite("wave5_decision_resolved", wave5_decision_ok, wave5_decision_detail)
    )
    if not wave5_decision_ok:
        blockers.append("wave5_decision_not_resolved")

    prerequisites.append(
        RolloutPrerequisite(
            "production_path_enabled",
            production_path,
            "isolated_parallel_write_production_path is enabled."
            if production_path
            else "Wave 6 requires Wave 5 L2 production path enabled.",
        )
    )
    if not production_path:
        blockers.append("production_path_not_enabled")

    dynamic_off = not dynamic_gray
    prerequisites.append(
        RolloutPrerequisite(
            "dynamic_gray_still_off",
            dynamic_off,
            "orchestration_dynamic_workflows_gray remains disabled before Wave 6 probe."
            if dynamic_off
            else "Dynamic gray already enabled; probe is idempotent re-verify only.",
        )
    )

    ready_for_decision = not blockers and all(item.ok for item in prerequisites[:-1])
    probe_blockers = list(blockers)
    if cli_parallel:
        probe_blockers.append("cli_parallel_writes_must_stay_off")
    ready_for_probe = ready_for_decision and not cli_parallel

    return Wave6DynamicReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_dynamic_probe=ready_for_probe,
        wave5_probe_ok=wave5_ok,
        wave5_decision_ok=wave5_decision_ok,
        production_path_enabled=production_path,
        dynamic_gray_enabled=dynamic_gray,
        cli_parallel_writes_default=cli_parallel,
        prerequisites=prerequisites,
        blockers=probe_blockers,
        wave5_readiness=wave5,
    )


def build_wave6_dynamic_decision_point(
    *,
    run_id: str,
    readiness: Wave6DynamicReadiness,
) -> dict[str, Any]:
    """DecisionPoint for Wave 6 L3 dynamic orchestration runner (CC mechanism; defaults unchanged)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": WAVE6_DECISION_ID,
        "status": "pending",
        "question": (
            "Enable L3 dynamic orchestration runner gray (CC Dynamic Workflows mechanism)? "
            "Plan lives in orchestration_manifest; runner state in JSONL — not AgentLoop context. "
            "CLI parallel_writes default stays false."
        ),
        "recommended_option_id": (
            "wave6_dynamic_workflows_gray" if readiness.ready_for_dynamic_probe else "defer"
        ),
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave6_dynamic_workflows_gray",
                "label": "Enable L3 dynamic orchestration runner gray",
                "tradeoff": "Maintainer manifest + runner with concurrency cap; not Beta default parallel.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep L3 dynamic gray off",
                "tradeoff": "Stop at Wave 5 L2 production path.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Rollback L3/L2 gray flags",
                "tradeoff": "Disable dynamic/workflows/production path flags.",
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
            "wave": 6,
            "layer": "L3_dynamic_orchestration",
            "requires_wave5_production_path": True,
            "cc_mechanism": "plan_in_manifest_state_in_runner",
            "cli_parallel_writes_unchanged": True,
            "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def set_orchestration_dynamic_workflows_gray(
    *,
    agent_dir: Path,
    validator: Any,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle L3 dynamic workflows gray without changing CLI parallel_writes default."""
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.json_store import JsonStore

    policy = load_policy_config(agent_dir, validator)
    agent_loop = dict(policy.get("agent_loop") or {})
    if bool(agent_loop.get("parallel_writes", False)):
        raise RuntimeError("Refusing dynamic workflows gray while agent_loop.parallel_writes is enabled.")
    if enabled and not bool(agent_loop.get(PRODUCTION_PATH_POLICY_KEY, False)):
        raise RuntimeError("Refusing dynamic workflows gray without isolated_parallel_write_production_path.")
    agent_loop[DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY] = enabled
    if MAX_PARALLEL_WORKERS_POLICY_KEY not in agent_loop:
        agent_loop[MAX_PARALLEL_WORKERS_POLICY_KEY] = 16
    policy = {**policy, "agent_loop": agent_loop}
    path = agent_dir / "policies.json"
    JsonStore(validator).write(path, policy, "policy_config")
    return policy


def run_wave6_dynamic_manifest_band(
    *,
    repo_root: Path,
    validator: Any,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Dry-run L3 manifest through runner; state under maintainer run_dir."""
    from asteria_runtime.core.orchestration_dynamic_runner import run_dynamic_orchestration
    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    gate_path = _resolve_wave6_gate_path(repo_root)
    if not gate_path.exists():
        return {"ok": False, "error": f"Missing Wave 6 gate: {gate_path}"}

    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    manifest_rel = gate.get("probe_manifest") or "benchmarks/orchestration_wave6_dynamic_manifest.json"
    manifest = manifest_path or (repo_root / manifest_rel)
    if not manifest.exists():
        return {"ok": False, "error": f"Missing probe manifest: {manifest}"}

    policy = load_policy_config(agent_dir, validator)
    run_id = f"run-wave6-dynamic-{now_iso().replace(':', '').replace('+', '')[:15]}"
    run_dir = agent_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = run_dynamic_orchestration(
        manifest_path=manifest,
        run_dir=run_dir,
        policy=policy,
        dry_run=True,
        resume=False,
    )

    resume_result = run_dynamic_orchestration(
        manifest_path=manifest,
        run_dir=run_dir,
        policy=policy,
        dry_run=True,
        resume=True,
    )

    resume_ok = resume_result.ok and resume_result.completed_steps == result.total_steps
    ok = result.ok and resume_ok
    return {
        "ok": ok,
        "layer": "L3_dynamic_orchestration",
        "mechanism": "manifest_plan_runner_state_jsonl",
        "dry_run": True,
        "initial_run": result.to_dict(),
        "resume_run": resume_result.to_dict(),
        "run_dir": str(run_dir),
        "manifest_path": str(manifest),
        "summary": (
            "Wave 6 L3 dynamic manifest band passed (dry-run + resume)."
            if ok
            else "Wave 6 dynamic manifest band failed."
        ),
    }


@dataclass(frozen=True)
class OrchestrationWave6DynamicResult:
    ok: bool
    decision: dict[str, Any]
    band: dict[str, Any]
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "band_ok": self.band.get("ok"),
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave6_dynamic_probe(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = WAVE6_DECISION_ID,
    selected_option_id: str = "wave6_dynamic_workflows_gray",
) -> OrchestrationWave6DynamicResult:
    """Resolve Wave 6 DecisionPoint and validate L3 dynamic orchestration runner."""
    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    policy = load_policy_config(agent_dir, validator)
    readiness = evaluate_wave6_dynamic_readiness(root=repo_root, policy=policy)
    if not readiness.ready_for_dynamic_probe and not readiness.dynamic_gray_enabled:
        blockers = ", ".join(readiness.blockers) or "Wave 6 not ready"
        raise RuntimeError(f"Wave 6 dynamic probe not ready: {blockers}")

    decision_path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not decision_path.exists():
        persist_orchestration_parallel_decision_point(
            agent_dir=agent_dir,
            validator=validator,
            decision_point=build_wave6_dynamic_decision_point(
                run_id="orchestration-wave6-dynamic-probe",
                readiness=readiness,
            ),
        )

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    band = run_wave6_dynamic_manifest_band(repo_root=repo_root, validator=validator)

    set_orchestration_dynamic_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)

    policy_after = load_policy_config(agent_dir, validator)
    agent_loop = policy_after.get("agent_loop") or {}
    defaults_ok = (
        not bool(agent_loop.get("parallel_writes"))
        and _real_disjoint_feature_default_off(policy_after)
    )
    ok = bool(band.get("ok")) and defaults_ok

    verification_dir = agent_dir / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = verification_dir / "orchestration_wave6_dynamic_probe.json"
    payload = {
        "schema_version": "0.1.0",
        "wave": 6,
        "layer": "L3_dynamic_orchestration",
        "ok": ok,
        "recorded_at": now_iso(),
        "decision_id": decision_id,
        "selected_option_id": selected_option_id,
        "dynamic_gray_policy_key": DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY,
        "max_parallel_workers_policy_key": MAX_PARALLEL_WORKERS_POLICY_KEY,
        "cli_parallel_writes_unchanged": not bool(agent_loop.get("parallel_writes")),
        "real_disjoint_default_unchanged": _real_disjoint_feature_default_off(policy_after),
        "cc_mechanism": "plan_in_manifest_state_in_runner_not_agent_loop_context",
        "band": band,
        "wave5_evidence_ref": str(DEFAULT_WAVE5_EVIDENCE),
        "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
    }
    evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        "Wave 6 L3 dynamic orchestration runner gray enabled; defaults unchanged."
        if ok
        else "Wave 6 dynamic probe failed; review evidence."
    )
    return OrchestrationWave6DynamicResult(
        ok=ok,
        decision=decision,
        band=band,
        evidence_path=evidence_dest,
        summary=summary,
    )


def _resolve_wave7_gate_path(root: Path) -> Path:
    local = root / "benchmarks" / "orchestration_wave7_live_gate.json"
    if local.exists():
        return local
    repo_gate = Path.cwd() / "benchmarks" / "orchestration_wave7_live_gate.json"
    if repo_gate.exists():
        return repo_gate
    return local


def load_wave6_decision(agent_dir: Path) -> dict[str, Any] | None:
    path = orchestration_parallel_decision_path(agent_dir, WAVE6_DECISION_ID)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def wave6_probe_passed(root: Path, *, wave6_evidence_path: Path | None = None) -> tuple[bool, str]:
    report = load_eval_report(wave6_evidence_path or (root / DEFAULT_WAVE6_EVIDENCE))
    if report is None:
        return False, "Missing Wave 6 dynamic probe evidence."
    if report.get("ok") is not True:
        return False, "Wave 6 dynamic probe evidence not ok."
    return True, "Wave 6 L3 dynamic runner probe passed."


def wave6_decision_resolved(agent_dir: Path) -> tuple[bool, str]:
    decision = load_wave6_decision(agent_dir)
    if decision is None:
        return False, f"Missing resolved Wave 6 decision: {WAVE6_DECISION_ID}."
    if decision.get("status") != "resolved":
        return False, f"Wave 6 decision not resolved: {WAVE6_DECISION_ID}."
    if decision.get("selected_option_id") != "wave6_dynamic_workflows_gray":
        return False, "Wave 6 decision did not select wave6_dynamic_workflows_gray."
    return True, "Wave 6 DecisionPoint resolved for L3 dynamic runner."


@dataclass(frozen=True)
class Wave7LiveExecutionReadiness:
    ready_for_decision_point: bool
    ready_for_live_probe: bool
    wave6_probe_ok: bool
    wave6_decision_ok: bool
    dynamic_gray_enabled: bool
    live_execution_enabled: bool
    cli_parallel_writes_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    wave6_readiness: Wave6DynamicReadiness | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_decision_point": self.ready_for_decision_point,
            "ready_for_live_probe": self.ready_for_live_probe,
            "wave6_probe_ok": self.wave6_probe_ok,
            "wave6_decision_ok": self.wave6_decision_ok,
            "dynamic_gray_enabled": self.dynamic_gray_enabled,
            "live_execution_enabled": self.live_execution_enabled,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
            "wave6_readiness": self.wave6_readiness.to_dict() if self.wave6_readiness else None,
        }


def evaluate_wave7_live_execution_readiness(
    *,
    root: Path,
    policy: dict[str, Any] | None = None,
    spawn_evidence_path: Path | None = None,
    route_evidence_path: Path | None = None,
    wave2_evidence_path: Path | None = None,
    wave3_evidence_path: Path | None = None,
    wave4_evidence_path: Path | None = None,
    wave5_evidence_path: Path | None = None,
    wave6_evidence_path: Path | None = None,
) -> Wave7LiveExecutionReadiness:
    """Assess Wave 7 L3 live execution readiness (does not enable live gray)."""
    root = root.resolve()
    agent_dir = root / ".asteria"
    policy = policy or {}
    agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
    dynamic_gray = bool(agent_loop.get(DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY, False))
    live_enabled = bool(agent_loop.get(LIVE_EXECUTION_GRAY_POLICY_KEY, False))
    cli_parallel = bool(agent_loop.get("parallel_writes", False))

    wave6 = evaluate_wave6_dynamic_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        wave2_evidence_path=wave2_evidence_path,
        wave3_evidence_path=wave3_evidence_path,
        wave4_evidence_path=wave4_evidence_path,
        wave5_evidence_path=wave5_evidence_path,
    )

    base = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=spawn_evidence_path,
        route_evidence_path=route_evidence_path,
        gray_drill_ok=True,
    )
    prerequisites: list[RolloutPrerequisite] = list(base.prerequisites)
    blockers = list(wave6.blockers)

    wave6_ok, wave6_detail = wave6_probe_passed(root, wave6_evidence_path=wave6_evidence_path)
    prerequisites.append(RolloutPrerequisite("wave6_dynamic_probe", wave6_ok, wave6_detail))
    if not wave6_ok:
        blockers.append("wave6_probe_missing_or_failed")

    wave6_decision_ok, wave6_decision_detail = wave6_decision_resolved(agent_dir)
    prerequisites.append(
        RolloutPrerequisite("wave6_decision_resolved", wave6_decision_ok, wave6_decision_detail)
    )
    if not wave6_decision_ok:
        blockers.append("wave6_decision_not_resolved")

    prerequisites.append(
        RolloutPrerequisite(
            "dynamic_workflows_gray_enabled",
            dynamic_gray,
            "orchestration_dynamic_workflows_gray is enabled."
            if dynamic_gray
            else "Wave 7 requires Wave 6 dynamic workflows gray.",
        )
    )
    if not dynamic_gray:
        blockers.append("dynamic_workflows_gray_not_enabled")

    live_off = not live_enabled
    prerequisites.append(
        RolloutPrerequisite(
            "live_execution_still_off",
            live_off,
            "orchestration_dynamic_live_execution_gray remains disabled before Wave 7 probe."
            if live_off
            else "Live execution gray already enabled; probe is idempotent re-verify only.",
        )
    )

    ready_for_decision = not blockers and all(item.ok for item in prerequisites[:-1])
    probe_blockers = list(blockers)
    if cli_parallel:
        probe_blockers.append("cli_parallel_writes_must_stay_off")
    ready_for_probe = ready_for_decision and not cli_parallel

    return Wave7LiveExecutionReadiness(
        ready_for_decision_point=ready_for_decision,
        ready_for_live_probe=ready_for_probe,
        wave6_probe_ok=wave6_ok,
        wave6_decision_ok=wave6_decision_ok,
        dynamic_gray_enabled=dynamic_gray,
        live_execution_enabled=live_enabled,
        cli_parallel_writes_default=cli_parallel,
        prerequisites=prerequisites,
        blockers=probe_blockers,
        wave6_readiness=wave6,
    )


def build_wave7_live_execution_decision_point(
    *,
    run_id: str,
    readiness: Wave7LiveExecutionReadiness,
) -> dict[str, Any]:
    """DecisionPoint for Wave 7 L3 live execution (CC workflow runtime; defaults unchanged)."""
    return {
        "schema_version": "0.1.0",
        "decision_id": WAVE7_DECISION_ID,
        "status": "pending",
        "question": (
            "Enable L3 dynamic orchestration live execution gray? "
            "Runner spawns readonly/disjoint workers; state stays in JSONL. "
            "CLI parallel_writes default stays false."
        ),
        "recommended_option_id": (
            "wave7_live_execution_gray" if readiness.ready_for_live_probe else "defer"
        ),
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "wave7_live_execution_gray",
                "label": "Enable L3 live execution maintainer gray",
                "tradeoff": "Real worker evidence under run_dir; L2 disjoint uses candidate + merge gate.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep live execution off (dry-run only)",
                "tradeoff": "Stop at Wave 6 L3 dry-run runner.",
                "action": "record_constraint",
            },
            {
                "option_id": "rollback_now",
                "label": "Rollback L3 live/dynamic gray flags",
                "tradeoff": "Disable live execution and dynamic workflow flags.",
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
            "wave": 7,
            "layer": "L3_dynamic_live_execution",
            "requires_wave6_dynamic_gray": True,
            "cc_mechanism": "workflow_runtime_executes_agents_state_in_runner",
            "cli_parallel_writes_unchanged": True,
            "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
            "readiness": readiness.to_dict(),
        },
        "resolved_at": None,
    }


def set_orchestration_dynamic_live_execution_gray(
    *,
    agent_dir: Path,
    validator: Any,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle L3 live execution gray without changing CLI parallel_writes default."""
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.storage.json_store import JsonStore

    policy = load_policy_config(agent_dir, validator)
    agent_loop = dict(policy.get("agent_loop") or {})
    if bool(agent_loop.get("parallel_writes", False)):
        raise RuntimeError("Refusing live execution gray while agent_loop.parallel_writes is enabled.")
    if enabled and not bool(agent_loop.get(DYNAMIC_WORKFLOWS_GRAY_POLICY_KEY, False)):
        raise RuntimeError("Refusing live execution gray without orchestration_dynamic_workflows_gray.")
    agent_loop[LIVE_EXECUTION_GRAY_POLICY_KEY] = enabled
    policy = {**policy, "agent_loop": agent_loop}
    path = agent_dir / "policies.json"
    JsonStore(validator).write(path, policy, "policy_config")
    return policy


def run_wave7_live_manifest_band(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Run L3 manifest with live worker execution (readonly + disjoint + merge checkpoint)."""
    from asteria_runtime.core.orchestration_dynamic_runner import run_dynamic_orchestration
    from asteria_runtime.core.policy_config import load_policy_config
    from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    gate_path = _resolve_wave7_gate_path(repo_root)
    if not gate_path.exists():
        return {"ok": False, "error": f"Missing Wave 7 gate: {gate_path}"}

    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    manifest_rel = gate.get("probe_manifest") or "benchmarks/orchestration_wave7_live_manifest.json"
    manifest = manifest_path or (repo_root / manifest_rel)
    if not manifest.exists():
        return {"ok": False, "error": f"Missing probe manifest: {manifest}"}

    policy = load_policy_config(agent_dir, validator)
    exec_policy = with_maintainer_probe_policy(policy)
    run_id = f"run-wave7-live-{now_iso().replace(':', '').replace('+', '')[:15]}"
    run_dir = agent_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = run_dynamic_orchestration(
        manifest_path=manifest,
        run_dir=run_dir,
        policy=exec_policy,
        dry_run=False,
        resume=False,
        root=repo_root,
        validator=validator,
        run_id=run_id,
    )

    workers_path = run_dir / "workers.jsonl"
    workers_ok = workers_path.exists() and workers_path.stat().st_size > 0
    state_path = run_dir / "orchestration_runner_state.jsonl"
    state_ok = state_path.exists() and state_path.stat().st_size > 0
    ok = result.ok and workers_ok and state_ok

    validation_path = persist_wave7_validation_run(agent_dir=agent_dir, band={
        "ok": ok,
        "live_run": result.to_dict(),
        "run_dir": str(run_dir),
        "workers_jsonl_present": workers_ok,
        "runner_state_present": state_ok,
    })

    return {
        "ok": ok,
        "layer": "L3_dynamic_live_execution",
        "mechanism": "live_readonly_fanout + live_disjoint_write_fanout + merge_checkpoint",
        "dry_run": False,
        "live_run": result.to_dict(),
        "run_dir": str(run_dir),
        "validation_run_path": str(validation_path),
        "manifest_path": str(manifest),
        "summary": (
            "Wave 7 L3 live execution band passed."
            if ok
            else "Wave 7 live execution band failed."
        ),
    }


def persist_wave7_validation_run(
    *,
    agent_dir: Path,
    band: dict[str, Any],
) -> Path:
    run_id = f"validation-wave7-l3-live-{now_iso().replace(':', '').replace('+', '')[:15]}"
    run_dir = agent_dir / "validation_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    payload = {
        "schema_version": "0.1.0",
        "validation_run_id": run_id,
        "purpose": "Wave 7 L3 dynamic orchestration live execution",
        "status": "completed" if band.get("ok") else "failed",
        "recorded_at": now_iso(),
        "wave": 7,
        "layer": "L3_live",
        "defaults_unchanged": {
            "cli_parallel_writes": False,
            "real_disjoint_write_workers": False,
        },
        "band": band,
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


@dataclass(frozen=True)
class OrchestrationWave7LiveResult:
    ok: bool
    decision: dict[str, Any]
    band: dict[str, Any]
    validation_run_path: Path | None
    evidence_path: Path | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision_id": self.decision.get("decision_id"),
            "selected_option_id": self.decision.get("selected_option_id"),
            "band_ok": self.band.get("ok"),
            "validation_run_path": str(self.validation_run_path) if self.validation_run_path else None,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "summary": self.summary,
        }


def run_orchestration_wave7_live_probe(
    *,
    repo_root: Path,
    validator: SchemaValidator,
    decision_id: str = WAVE7_DECISION_ID,
    selected_option_id: str = "wave7_live_execution_gray",
) -> OrchestrationWave7LiveResult:
    """Resolve Wave 7 DecisionPoint and validate L3 live execution band."""
    from asteria_runtime.core.policy_config import load_policy_config

    repo_root = repo_root.resolve()
    agent_dir = repo_root / ".asteria"
    if not agent_dir.exists():
        raise RuntimeError("Repository .asteria not initialized.")

    policy = load_policy_config(agent_dir, validator)
    readiness = evaluate_wave7_live_execution_readiness(root=repo_root, policy=policy)
    if not readiness.ready_for_live_probe and not readiness.live_execution_enabled:
        blockers = ", ".join(readiness.blockers) or "Wave 7 not ready"
        raise RuntimeError(f"Wave 7 live probe not ready: {blockers}")

    decision_path = orchestration_parallel_decision_path(agent_dir, decision_id)
    if not decision_path.exists():
        persist_orchestration_parallel_decision_point(
            agent_dir=agent_dir,
            validator=validator,
            decision_point=build_wave7_live_execution_decision_point(
                run_id="orchestration-wave7-live-probe",
                readiness=readiness,
            ),
        )

    decision = resolve_orchestration_parallel_decision(
        agent_dir=agent_dir,
        validator=validator,
        decision_id=decision_id,
        selected_option_id=selected_option_id,
    )

    band = run_wave7_live_manifest_band(repo_root=repo_root, validator=validator)
    validation_path = Path(band["validation_run_path"]) if band.get("validation_run_path") else None

    set_orchestration_dynamic_live_execution_gray(
        agent_dir=agent_dir, validator=validator, enabled=True
    )

    policy_after = load_policy_config(agent_dir, validator)
    agent_loop = policy_after.get("agent_loop") or {}
    defaults_ok = (
        not bool(agent_loop.get("parallel_writes"))
        and _real_disjoint_feature_default_off(policy_after)
    )
    ok = bool(band.get("ok")) and defaults_ok

    verification_dir = agent_dir / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = verification_dir / "orchestration_wave7_live_probe.json"
    payload = {
        "schema_version": "0.1.0",
        "wave": 7,
        "layer": "L3_dynamic_live_execution",
        "ok": ok,
        "recorded_at": now_iso(),
        "decision_id": decision_id,
        "selected_option_id": selected_option_id,
        "live_execution_gray_policy_key": LIVE_EXECUTION_GRAY_POLICY_KEY,
        "cli_parallel_writes_unchanged": not bool(agent_loop.get("parallel_writes")),
        "real_disjoint_default_unchanged": _real_disjoint_feature_default_off(policy_after),
        "cc_mechanism": "workflow_runtime_executes_workers_state_in_runner_jsonl",
        "band": band,
        "validation_run_path": str(validation_path) if validation_path else None,
        "wave6_evidence_ref": str(DEFAULT_WAVE6_EVIDENCE),
        "reference_alignment": "docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md",
    }
    evidence_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        "Wave 7 L3 live execution gray enabled; defaults unchanged."
        if ok
        else "Wave 7 live probe failed; review validation_run evidence."
    )
    return OrchestrationWave7LiveResult(
        ok=ok,
        decision=decision,
        band=band,
        validation_run_path=validation_path,
        evidence_path=evidence_dest,
        summary=summary,
    )
