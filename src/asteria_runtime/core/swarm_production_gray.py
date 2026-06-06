from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from asteria_runtime.core.swarm_gray_decision import run_gray_rollback_drill
from asteria_runtime.core.swarm_scenario_audit import SwarmScenarioAuditor
from asteria_runtime.core.swarm_flag_rollout import (
    RolloutPrerequisite,
    evaluate_rollout_readiness,
    maintainer_probe_environment,
)
from asteria_runtime.core.worker_spawn import REAL_DISJOINT_WRITE_FLAG
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.utils.time import now_iso


PRODUCTION_GRAY_DECISION_KIND = "swarm_production_gray"
PRODUCTION_GRAY_EVIDENCE_FILE = "production_gray_evidence.json"
_DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "templates" / "policies.default.json"


def _production_gray_base_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    if policy:
        return policy
    return json.loads(_DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


class ExecuteModelClient(Protocol):
    def chat(self, request: Any) -> Any: ...


@dataclass(frozen=True)
class ProductionGrayReadinessResult:
    ready: bool
    flag_name: str
    cli_parallel_writes_default: bool
    prerequisites: list[RolloutPrerequisite] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    dual_worker_case_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "flag_name": self.flag_name,
            "cli_parallel_writes_default": self.cli_parallel_writes_default,
            "dual_worker_case_id": self.dual_worker_case_id,
            "prerequisites": [item.to_dict() for item in self.prerequisites],
            "blockers": self.blockers,
        }


@dataclass(frozen=True)
class DualDisjointScenarioResult:
    ok: bool
    run_id: str
    run_dir: Path
    audit_ok: bool
    detected_paths: list[str]
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "audit_ok": self.audit_ok,
            "detected_paths": self.detected_paths,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ProductionGrayBandResult:
    ok: bool
    execute: DualDisjointScenarioResult
    gray_drill_ok: bool
    readiness: ProductionGrayReadinessResult
    decision_point: dict[str, Any]
    evidence_path: Path
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "execute": self.execute.to_dict(),
            "gray_drill_ok": self.gray_drill_ok,
            "readiness": self.readiness.to_dict(),
            "decision_point_id": self.decision_point.get("decision_id"),
            "evidence_path": str(self.evidence_path),
            "summary": self.summary,
        }


def _benchmarks_root(root: Path | None = None) -> Path:
    candidate = root or Path.cwd()
    if (candidate / "benchmarks" / "phase5_dual_worker_case.json").exists():
        return candidate
    return Path.cwd()


def load_dual_worker_case(root: Path | None = None) -> dict[str, Any]:
    repo = _benchmarks_root(root)
    path = repo / "benchmarks" / "phase5_dual_worker_case.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_production_gray_gate(root: Path | None = None) -> dict[str, Any]:
    repo = _benchmarks_root(root)
    path = repo / "benchmarks" / "phase5f_production_gray_gate.json"
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_production_gray_readiness(
    policy: dict[str, Any] | None,
    *,
    gray_rollback_drill_ok: bool = False,
    scenario_gate_ok: bool = True,
    dual_worker_audit_ok: bool = False,
    dual_worker_case_signed: bool = False,
    environment: dict[str, bool] | None = None,
    cli_parallel_writes_default: bool = False,
) -> ProductionGrayReadinessResult:
    """Assess whether scoped production gray may proceed (not CLI default flip)."""
    gate = load_production_gray_gate()
    case = load_dual_worker_case()
    production = gate.get("production_gray") or {}
    flag_name = str(production.get("flag_name") or REAL_DISJOINT_WRITE_FLAG)

    prerequisites: list[RolloutPrerequisite] = []
    blockers: list[str] = []

    prerequisites.append(
        RolloutPrerequisite(
            "cli_parallel_writes_default_off",
            cli_parallel_writes_default is False,
            "CLI parallel_writes must remain false for Beta defaults."
            if cli_parallel_writes_default is False
            else "CLI parallel_writes default must not flip in S34.",
        )
    )
    if cli_parallel_writes_default:
        blockers.append("cli_parallel_writes_default_on")

    prerequisites.append(
        RolloutPrerequisite(
            "gray_rollback_drill",
            gray_rollback_drill_ok,
            "S32 gray rollback drill evidence required before production gray."
            if gray_rollback_drill_ok
            else "Run gray rollback drill (phase5e) before production gray.",
        )
    )
    if not gray_rollback_drill_ok:
        blockers.append("gray_rollback_drill_missing")

    prerequisites.append(
        RolloutPrerequisite(
            "phase5_scenario_gate",
            scenario_gate_ok,
            "Phase 5d unified scenario gate must be signed."
            if scenario_gate_ok
            else "phase5d scenario gate missing or failing.",
        )
    )
    if not scenario_gate_ok:
        blockers.append("phase5_scenario_gate_missing")

    prerequisites.append(
        RolloutPrerequisite(
            "dual_worker_execute_audit",
            dual_worker_audit_ok,
            "Dual worker execute_parallel_disjoint audit passed."
            if dual_worker_audit_ok
            else "Run dual_disjoint_files execute scenario before production gray.",
        )
    )
    if not dual_worker_audit_ok:
        blockers.append("dual_worker_audit_missing")

    prerequisites.append(
        RolloutPrerequisite(
            "dual_worker_case_contract",
            bool(case.get("case_id")),
            f"Dual worker case contract loaded ({case.get('case_id')})."
            if case.get("case_id")
            else "phase5_dual_worker_case.json missing case_id.",
        )
    )
    if not case.get("case_id"):
        blockers.append("dual_worker_case_missing")

    signoff = gate.get("real_provider_signoff") or {}
    if signoff.get("optional") and not dual_worker_case_signed:
        prerequisites.append(
            RolloutPrerequisite(
                "dual_worker_real_signoff",
                True,
                "Real provider dual worker signoff optional for CI; required for maintainer close.",
            )
        )
    else:
        prerequisites.append(
            RolloutPrerequisite(
                "dual_worker_real_signoff",
                dual_worker_case_signed,
                "Real provider dual_disjoint_files signoff recorded."
                if dual_worker_case_signed
                else "Real provider dual worker case not signed.",
            )
        )
        if not dual_worker_case_signed:
            blockers.append("dual_worker_unsigned")

    rollout = evaluate_rollout_readiness(
        policy,
        target_enabled=True,
        environment=environment,
        phase5_entry_signed=True,
    )
    prerequisites.extend(rollout.prerequisites)
    blockers.extend(rollout.blockers)

    ready = not blockers and all(item.ok for item in prerequisites)
    return ProductionGrayReadinessResult(
        ready=ready,
        flag_name=flag_name,
        cli_parallel_writes_default=cli_parallel_writes_default,
        prerequisites=prerequisites,
        blockers=list(dict.fromkeys(blockers)),
        dual_worker_case_id=str(case.get("case_id") or "") or None,
    )


def build_production_gray_decision_point(*, run_id: str, sequence: int = 1) -> dict[str, Any]:
    case = load_dual_worker_case()
    return {
        "schema_version": "0.1.0",
        "decision_id": f"decision-production-gray-{max(1, sequence):04d}",
        "status": "pending",
        "question": (
            f"Enable scoped production gray for {case.get('case_id')} after prerequisites? "
            "Beta default remains session_agent; CLI parallel_writes stays off."
        ),
        "recommended_option_id": "approve_scoped_gray",
        "default_option_id": "defer",
        "options": [
            {
                "option_id": "approve_scoped_gray",
                "label": "Approve scoped production gray run",
                "tradeoff": "Allows explicit parallel_writes harness runs with DecisionPoint audit.",
                "action": "create_task",
            },
            {
                "option_id": "defer",
                "label": "Keep production gray blocked",
                "tradeoff": "Continue session_agent defaults until maintainer re-evaluates.",
                "action": "record_constraint",
            },
        ],
        "impact": {"scope": "high", "budget": "medium", "risk": "high", "quality": "medium"},
        "selected_option_id": None,
        "created_at": now_iso(),
        "metadata": {
            "kind": PRODUCTION_GRAY_DECISION_KIND,
            "run_id": run_id,
            "case_id": case.get("case_id"),
            "flag_name": REAL_DISJOINT_WRITE_FLAG,
            "cli_parallel_writes_unchanged": True,
        },
        "resolved_at": None,
    }


def prepare_dual_disjoint_task_plan(run_dir: Path) -> None:
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    base = {
        "schema_version": "0.1.0",
        "description": "Write an independent output file.",
        "status": "ready",
        "priority": "medium",
        "role": "CoderAgent",
        "depends_on": [],
        "acceptance": ["output file exists"],
        "allowed_tools": ["write_file", "run_command"],
        "expected_artifacts": [],
        "task_kind": "implementation",
        "parallel_safety": "disjoint_writes",
        "execution_profile": "harness",
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "notes": "S34 dual_disjoint_files scenario.",
    }
    task_plan["tasks"] = [
        {
            **base,
            "task_id": "task-0001",
            "title": "Write alpha",
            "write_scope": ["out/alpha.txt"],
            "expected_changed_files": ["out/alpha.txt"],
        },
        {
            **base,
            "task_id": "task-0002",
            "title": "Write beta",
            "write_scope": ["out/beta.txt"],
            "expected_changed_files": ["out/beta.txt"],
        },
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False, indent=2), encoding="utf-8")


class MaintainerDisjointExecuteClient:
    """Deterministic execute client for maintainer dual-disjoint scenarios."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        path = "out/alpha.txt" if task_id == "task-0001" else "out/beta.txt"
        payload = {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "summary": f"Write {path}.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "args": {"path": path, "content": task_id, "overwrite": True},
                    "reason": "write disjoint output",
                }
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            'python -c "from pathlib import Path; '
                            f"assert Path('{path}').read_text() == '{task_id}'\""
                        )
                    },
                    "reason": "verify disjoint output",
                }
            ],
            "completion_notes": f"{path} written",
        }
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="maintainer-disjoint-execute",
            raw_response={},
        )


class MaintainerDualDisjointPlanClient:
    """Minimal plan client for dual-disjoint execute scenarios."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-dual-disjoint",
                    "original_goal": "write two independent outputs",
                    "normalized_goal": "Write two independent outputs in parallel harness workers",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": ["local_first"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Write out/alpha.txt and out/beta.txt via disjoint workers",
                            "acceptance": ["both files exist"],
                        }
                    ],
                    "target_outputs": ["out/alpha.txt", "out/beta.txt"],
                    "definition_of_done": ["both outputs promoted"],
                    "verification_strategy": [],
                    "budget": {"max_iterations": 4, "max_model_calls": 20},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="maintainer-dual-disjoint-plan",
            raw_response={},
        )


def run_dual_disjoint_execute_scenario(
    root: Path,
    validator: SchemaValidator,
    *,
    execute_client: ExecuteModelClient | None = None,
    plan_client: ExecuteModelClient | None = None,
) -> DualDisjointScenarioResult:
    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.commands.plan_command import PlanCommand

    root.mkdir(parents=True, exist_ok=True)
    InitCommand(root).run()
    plan = PlanCommand(
        root,
        "write two independent outputs",
        model_client=plan_client or MaintainerDualDisjointPlanClient(),
    ).run()
    run_dir = root / ".asteria" / "runs" / plan.run_id
    prepare_dual_disjoint_task_plan(run_dir)
    ExecuteCommand(
        root,
        run_id=plan.run_id,
        max_tasks=2,
        model_client=execute_client or MaintainerDisjointExecuteClient(),
        parallel_writes=True,
    ).run()
    audit = SwarmScenarioAuditor(validator).evaluate_run_dir(run_dir)
    ok = audit.ok and "execute_parallel_disjoint" in audit.detected_paths
    return DualDisjointScenarioResult(
        ok=ok,
        run_id=plan.run_id,
        run_dir=run_dir,
        audit_ok=audit.ok,
        detected_paths=audit.detected_paths,
        summary=audit.summary,
    )


def run_production_gray_band(
    root: Path,
    validator: SchemaValidator,
    *,
    policy: dict[str, Any] | None = None,
    execute_client: ExecuteModelClient | None = None,
    dual_worker_case_signed: bool = False,
) -> ProductionGrayBandResult:
    """Full S34 band: dual execute scenario → gray drill → readiness → DecisionPoint evidence."""
    base_policy = _production_gray_base_policy(policy)
    execute = run_dual_disjoint_execute_scenario(
        root,
        validator,
        execute_client=execute_client,
    )
    gray_run_dir = root / ".asteria" / "runs" / f"{execute.run_id}-gray"
    gray = run_gray_rollback_drill(
        root=root,
        run_dir=gray_run_dir,
        run_id=f"{execute.run_id}-gray",
        validator=validator,
        policy=base_policy,
    )
    readiness = evaluate_production_gray_readiness(
        base_policy,
        gray_rollback_drill_ok=gray.ok,
        scenario_gate_ok=True,
        dual_worker_audit_ok=execute.ok,
        dual_worker_case_signed=dual_worker_case_signed,
        environment=maintainer_probe_environment(),
        cli_parallel_writes_default=False,
    )
    decision = build_production_gray_decision_point(run_id=execute.run_id)
    JsonlStore(validator).append(
        execute.run_dir / "decisions.jsonl",
        decision,
        "decision_point",
    )
    evidence = {
        "schema_version": "0.1.0",
        "case_id": load_dual_worker_case(root).get("case_id"),
        "run_id": execute.run_id,
        "recorded_at": now_iso(),
        "ok": execute.ok and gray.ok and readiness.ready,
        "execute_parallel_disjoint": execute.ok,
        "gray_rollback_drill_ok": gray.ok,
        "readiness": readiness.to_dict(),
        "detected_paths": execute.detected_paths,
        "cli_parallel_writes_default": False,
        "summary": (
            "Production gray band passed."
            if execute.ok and gray.ok and readiness.ready
            else "Production gray band blocked."
        ),
    }
    evidence_path = execute.run_dir / PRODUCTION_GRAY_EVIDENCE_FILE
    JsonStore(validator).write(evidence_path, evidence, schema_name=None)
    ok = bool(evidence["ok"])
    return ProductionGrayBandResult(
        ok=ok,
        execute=execute,
        gray_drill_ok=gray.ok,
        readiness=readiness,
        decision_point=decision,
        evidence_path=evidence_path,
        summary=str(evidence["summary"]),
    )


def find_production_gray_evidence(root: Path) -> dict[str, Any] | None:
    runs_root = root / ".asteria" / "runs"
    if not runs_root.is_dir():
        return None
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        path = run_dir / PRODUCTION_GRAY_EVIDENCE_FILE
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("ok"):
            return payload
    return None
