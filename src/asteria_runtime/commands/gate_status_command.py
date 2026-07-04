from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from asteria_runtime.commands._runtime_os_helpers import runtime_os_release_evidence
from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.flag_resolver import FlagResolver
from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.real_provider_matrix import (
    latest_real_provider_matrix,
    real_provider_matrix_text_lines,
)
from asteria_runtime.core.recovery_pressure import (
    recovery_pressure_report,
    recovery_pressure_text_lines,
)
from asteria_runtime.core.runtime_validation_matrix import (
    runtime_validation_matrix,
    runtime_validation_matrix_text_lines,
)
from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.core.agent_loop_decision import (
    latest_agent_loop_decision,
    recommended_command_for_next_action,
)
from asteria_runtime.core.agent_loop_executor import latest_agent_loop_execution_result
from asteria_runtime.real_model_acceptance import SUITES as REAL_MODEL_ACCEPTANCE_SUITES
from asteria_runtime.models.route_diagnostics import (
    route_diagnostic_for_tier,
    route_environment_for_tiers,
)
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class GateStatusResult:
    root: Path
    stage: str
    gate_report: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    core_report: dict[str, Any] = field(default_factory=dict)
    route_environment: dict[str, Any] = field(default_factory=dict)
    route_guidance: dict[str, Any] = field(default_factory=dict)
    route_table: dict[str, Any] = field(default_factory=dict)
    model_call_contract: dict[str, Any] = field(default_factory=dict)
    latest_observation_plan: dict[str, Any] = field(default_factory=dict)
    latest_real_provider_matrix: dict[str, Any] = field(default_factory=dict)
    promotion_release_risks: dict[str, Any] = field(default_factory=dict)
    plugin_risks: dict[str, Any] = field(default_factory=dict)
    runtime_progress_metrics: dict[str, Any] = field(default_factory=dict)
    runtime_validation_matrix: dict[str, Any] = field(default_factory=dict)
    v0_2_rolling_validation: dict[str, Any] = field(default_factory=dict)
    recovery_pressure: dict[str, Any] = field(default_factory=dict)
    context_pressure_summary: dict[str, Any] = field(default_factory=dict)
    validation_recommendation: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, Any] = field(default_factory=dict)
    capability_flags: dict[str, Any] = field(default_factory=dict)
    evidence_sources: dict[str, str] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        release_state = self._release_state()
        blocking_reason = (
            None
            if release_state == "release_ready"
            else (self.next_actions[0] if self.next_actions else None)
        )
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="gate-status",
                audience="maintainer_release_validation",
                stable_fields=[
                    "schema_version",
                    "root",
                    "stage",
                    "release_state",
                    "release_ready",
                    "blocking_reason",
                    "gates",
                    "route_environment",
                    "route_guidance",
                    "route_table",
                    "model_call_contract",
                    "latest_observation_plan",
                    "latest_real_provider_matrix",
                    "promotion_release_risks",
                    "plugin_risks",
                    "runtime_progress_metrics",
                    "runtime_validation_matrix",
                    "v0_2_rolling_validation",
                    "readiness_explanation",
                    "recovery_pressure",
                    "context_pressure_summary",
                    "feature_flags",
                    "capability_flags",
                    "evidence_sources",
                    "validation_task_limits",
                    "validation_recommendation",
                    "next_actions",
                ],
            ),
            "root": str(self.root),
            "stage": self.stage,
            "release_state": release_state,
            "release_ready": release_state == "release_ready",
            "blocking_reason": blocking_reason,
            "gates": {
                "real_model_gate": self._gate_summary(self.gate_report),
                "validation_suite": self._gate_summary(self.validation_report, validation=True),
                "core_acceptance": self._gate_summary(self.core_report),
            },
            "route_environment": self.route_environment,
            "route_guidance": self.route_guidance,
            "route_table": self.route_table,
            "model_call_contract": self.model_call_contract,
            "latest_observation_plan": self.latest_observation_plan,
            "latest_real_provider_matrix": self.latest_real_provider_matrix,
            "promotion_release_risks": self.promotion_release_risks,
            "plugin_risks": self.plugin_risks,
            "runtime_progress_metrics": self.runtime_progress_metrics,
            "runtime_validation_matrix": self.runtime_validation_matrix,
            "v0_2_rolling_validation": self.v0_2_rolling_validation,
            "readiness_explanation": self._readiness_explanation(release_state),
            "recovery_pressure": self.recovery_pressure,
            "context_pressure_summary": self.context_pressure_summary,
            "feature_flags": self.feature_flags,
            "capability_flags": self.capability_flags,
            "evidence_sources": self.evidence_sources,
            "validation_task_limits": _validation_task_limits(),
            "validation_recommendation": self.validation_recommendation,
            "gate_report": self.gate_report,
            "validation_report": self.validation_report,
            "core_report": self.core_report,
            "next_actions": self.next_actions,
        }

    def _release_state(self) -> str:
        if self.stage in {
            "current_environment_incomplete",
            "route_guidance_blocked",
            "model_call_contract_blocked",
            "candidate_promotion_risk_blocked",
            "plugin_manifests_blocked",
        }:
            return "blocked"
        if self.stage == "ready_for_small_real_task_validation":
            return "release_ready"
        if self.stage in {"ready_for_validation_suite", "ready_for_core_acceptance"}:
            return "conditional"
        return "blocked"

    def _gate_summary(self, report: dict[str, Any], validation: bool = False) -> dict[str, Any]:
        if not report:
            return {"present": False, "ok": None, "status": "missing"}
        summary: dict[str, Any] = {
            "present": True,
            "ok": bool(report.get("ok")),
            "status": "pass" if report.get("ok") else "fail",
        }
        aggregate = report.get("aggregate")
        if isinstance(aggregate, dict):
            summary["total"] = int(aggregate.get("total") or 0)
            summary["passed"] = int(aggregate.get("passed") or 0)
            summary["failed"] = int(aggregate.get("failed") or 0)
        if validation:
            summary["validation_ready"] = report.get("validation_ready")
            route = aggregate.get("route_evidence") if isinstance(aggregate, dict) else {}
            if isinstance(route, dict):
                summary["route_evidence"] = route
        return summary

    def to_text(self) -> str:
        lines = [
            "Gate status",
            f"Root: {self.root}",
            f"Stage: {self.stage}",
            f"Release state: {self._release_state()}",
        ]
        if self.route_environment:
            lines.append(
                "Current routes: "
                f"strong={self.route_environment.get('strong', {}).get('configured', False)}, "
                f"medium={self.route_environment.get('medium', {}).get('configured', False)}"
            )
        if self.route_guidance:
            lines.append(f"Route guidance: {self.route_guidance.get('status', 'unknown')}")
        if self.route_table:
            tiers = self.route_table.get("tiers", {})
            lines.append(
                "Model routes: "
                + ", ".join(
                    f"{tier}={route.get('provider', '?')}"
                    for tier, route in tiers.items()
                )
            )
            offline = self.route_table.get("offline_tiers") or []
            if offline:
                lines.append(
                    "Offline tiers (return canned output; set AGENT_MODEL_<TIER>_PROVIDER "
                    f"to a real provider): {', '.join(offline)}"
                )
        if self.model_call_contract:
            lines.append(
                "Model call contract: "
                f"{self.model_call_contract.get('status', 'unknown')} "
                f"({self.model_call_contract.get('checked_calls', 0)} checked)"
            )
        if self.latest_observation_plan:
            lines.append(
                "Latest agent next action: "
                f"{self.latest_observation_plan.get('recommended_route', 'unknown')} - "
                f"{self.latest_observation_plan.get('reason', 'No reason recorded.')}"
            )
        lines.extend(real_provider_matrix_text_lines(self.latest_real_provider_matrix))
        lines.extend(runtime_validation_matrix_text_lines(self.runtime_validation_matrix))
        if self.v0_2_rolling_validation:
            coverage = self.v0_2_rolling_validation.get("coverage") or {}
            covered = [name for name, ok in coverage.items() if ok]
            missing = self.v0_2_rolling_validation.get("missing_evidence_categories") or []
            lines.append(
                "v0.2 rolling validation: "
                f"{self.v0_2_rolling_validation.get('status', 'unknown')} "
                f"({self.v0_2_rolling_validation.get('sample_count', 0)} sample(s), "
                f"covered={','.join(covered) or 'none'}, "
                f"missing={','.join(str(item) for item in missing) or 'none'})"
            )
        explanation = self._readiness_explanation(self._release_state())
        if explanation:
            lines.append(
                f"Readiness explanation: {explanation.get('status')} - {explanation.get('summary')}"
            )
        lines.extend(recovery_pressure_text_lines(self.recovery_pressure))
        if self.context_pressure_summary:
            lines.append(
                "Context pressure: "
                f"{self.context_pressure_summary.get('max_context_estimated_tokens', 0)} tokens "
                f"({self.context_pressure_summary.get('max_context_window_ratio', 0.0):.2f} window ratio)"
            )
            subagent = self.context_pressure_summary.get("subagent_child_context") or {}
            if subagent:
                lines.append(
                    "Subagent context: "
                    f"{subagent.get('pressure_status', 'unknown')} "
                    f"({subagent.get('estimated_tokens', 0)} tokens, "
                    f"duplicate={subagent.get('duplicate_estimated_tokens', 0)})"
                )
            sections = self.context_pressure_summary.get("sections") or {}
            if sections:
                top_sections = sorted(sections.items(), key=lambda item: (-item[1], item[0]))[:5]
                lines.append(
                    "Context sections: "
                    + ", ".join(f"{name}={tokens}" for name, tokens in top_sections)
                )
        if self.feature_flags:
            active = [n for n, v in self.feature_flags.items() if v.get("active")]
            lines.append(f"Feature flags: {len(active)} active of {len(self.feature_flags)}")
        if self.capability_flags:
            available = [n for n, v in self.capability_flags.items() if v.get("available")]
            lines.append(
                f"Capabilities: {len(available)} available of {len(self.capability_flags)}"
            )
        if self.evidence_sources:
            lines.append("Evidence sources:")
            for name, source in sorted(self.evidence_sources.items()):
                lines.append(f"  - {name}: {source}")
        if self.promotion_release_risks:
            lines.append(
                "Promotion risks: "
                f"pending={self.promotion_release_risks.get('pending', 0)}, "
                f"blocked={self.promotion_release_risks.get('blocked', 0)}"
            )
        if self.runtime_progress_metrics:
            profile = self.runtime_progress_metrics.get("profile_coverage") or {}
            permission = self.runtime_progress_metrics.get("permission_reason_coverage") or {}
            progress = self.runtime_progress_metrics.get("runtime_native_progress_coverage") or {}
            adapters = self.runtime_progress_metrics.get("adapter_invocation_coverage") or {}
            lines.append(
                "Runtime progress metrics: "
                f"profiles={profile.get('coverage_ratio', 0)}, "
                f"permission_reasons={permission.get('coverage_ratio', 0)}, "
                f"user_progress={progress.get('coverage_ratio', 0)}"
            )
            lines.append(
                "Capability adapter evidence: "
                f"mcp={adapters.get('mcp_invocation_count', 0)}, "
                f"skills={adapters.get('skill_invocation_count', 0)}, "
                f"progress_events={adapters.get('capability_progress_event_count', 0)}"
            )
        lines.extend(self._report_lines("Real model gate", self.gate_report))
        lines.extend(
            self._report_lines("Validation suite", self.validation_report, validation=True)
        )
        lines.extend(self._report_lines("Core acceptance", self.core_report))
        if self.next_actions:
            lines.append("Recommended next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        if self.validation_recommendation:
            lines.append("Recommended validation:")
            lines.append(f"  - level: {self.validation_recommendation.get('level')}")
            lines.append(f"  - command: {self.validation_recommendation.get('command')}")
        limits = _validation_task_limits()
        lines.append("Small validation task limits:")
        lines.append(f"  - max_iterations: {limits['max_iterations']}")
        lines.append(f"  - max_tasks_per_iteration: {limits['max_tasks_per_iteration']}")
        lines.append(f"  - max_repairs: {limits['max_repairs']}")
        return "\n".join(lines)

    def _report_lines(
        self, label: str, report: dict[str, Any], validation: bool = False
    ) -> list[str]:
        if not report:
            return [f"{label}: missing"]
        status = "pass" if report.get("ok") else "fail"
        lines = [f"{label}: {status}"]
        if validation and "validation_ready" in report:
            lines.append(f"  validation_ready: {report.get('validation_ready')}")
        aggregate = report.get("aggregate")
        if isinstance(aggregate, dict):
            lines.append(
                f"  scenarios: {aggregate.get('passed', 0)}/{aggregate.get('total', 0)} passed"
            )
            route = aggregate.get("route_evidence")
            if isinstance(route, dict):
                lines.append(
                    "  routes: "
                    f"strong={route.get('strong_used', False)}, "
                    f"medium={route.get('medium_used', False)}"
                )
        failures = report.get("failures")
        if isinstance(failures, list) and failures:
            lines.append("  failures: " + "; ".join(str(item) for item in failures[:3]))
        return lines

    def _readiness_explanation(self, release_state: str) -> dict[str, Any]:
        matrix = self.runtime_validation_matrix or {}
        gap_summary = matrix.get("gap_summary") if isinstance(matrix, dict) else {}
        gap_summary = gap_summary if isinstance(gap_summary, dict) else {}
        gates = {
            "real_model_gate": self._gate_summary(self.gate_report),
            "validation_suite": self._gate_summary(self.validation_report, validation=True),
            "core_acceptance": self._gate_summary(self.core_report),
        }
        if release_state == "release_ready":
            summary = "release gates and current runtime evidence are ready for small validation."
            status = "ready"
        elif self.stage in {"ready_for_validation_suite", "ready_for_core_acceptance"}:
            summary = "release gates are partially satisfied; more suite evidence is required."
            status = "missing_release_suite_evidence"
        elif self.stage == "validation_suite_failed":
            summary = "validation suite evidence is present but did not complete successfully."
            status = "validation_suite_failed"
        elif int(gap_summary.get("implementation_missing") or 0) > 0:
            summary = "runtime matrix found missing implementation coverage."
            status = "implementation_gap"
        elif int(gap_summary.get("evidence_missing") or 0) > 0:
            summary = "runtime implementation exists, but validation evidence is missing."
            status = "evidence_gap"
        elif int(gap_summary.get("historical_evidence_noise") or 0) > 0:
            summary = "historical run evidence is noisy; collect focused runtime matrix evidence."
            status = "historical_evidence_noise"
        elif self.route_guidance.get("status") == "blocked":
            summary = "provider route health is blocked by recent capability evidence."
            status = "route_health_blocked"
        else:
            summary = self.next_actions[0] if self.next_actions else "gate is blocked."
            status = "blocked"
        return {
            "status": status,
            "summary": summary,
            "stage": self.stage,
            "release_state": release_state,
            "gate_statuses": gates,
            "runtime_validation_gap_summary": gap_summary,
            "route_guidance_status": self.route_guidance.get("status"),
            "v0_2_rolling_validation_status": self.v0_2_rolling_validation.get("status"),
        }


class GateStatusCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> GateStatusResult:
        gate_path = self.root / ".asteria" / "model" / "real_model_gate_report.json"
        gate = self._read_json(gate_path)
        validation, validation_path = self._latest_acceptance_report("validation")
        core, core_path = self._latest_acceptance_report("core")
        if not core:
            fallback_core_path = self.root / ".asteria" / "acceptance" / "acceptance_report.json"
            core = self._read_json(fallback_core_path)
            core_path = fallback_core_path if core else None
        stage, actions = self._stage(gate, validation, core)
        route_environment = _route_environment()
        route_table = _route_table()
        route_guidance = _route_guidance(self.root)
        route_guidance = _release_evidence_route_guidance(route_guidance, gate, validation, core)
        model_call_contract = _model_call_contract(self.root, self.validator, gate)
        latest_observation_plan = _latest_observation_plan(self.root, self.validator)
        latest_observation_plan = _current_release_observation_plan(
            latest_observation_plan,
            validation_path,
            core_path,
        )
        latest_matrix = latest_real_provider_matrix(self.root / ".asteria")
        matrix_actions = _real_provider_matrix_next_actions(latest_matrix) if latest_matrix else []
        if matrix_actions:
            actions = [
                *matrix_actions,
                *actions,
            ]
        promotion_release_risks = _promotion_release_risks(self.root, self._policy())
        if stage == "ready_for_small_real_task_validation" and not route_environment["ready"]:
            stage = "current_environment_incomplete"
            missing = ", ".join(route_environment["missing_required"])
            actions = [
                f"Set current model route environment variables before validation: {missing}.",
                *actions,
            ]
        if (
            stage == "ready_for_small_real_task_validation"
            and model_call_contract.get("status") == "blocked"
        ):
            stage = "model_call_contract_blocked"
            actions = [
                "Refresh real-provider evidence so recent model_calls include role contract, deadline, and streaming telemetry.",
                *[str(item) for item in model_call_contract.get("recommended_actions", [])],
                *actions,
            ]
        if (
            stage == "ready_for_small_real_task_validation"
            and route_guidance.get("status") == "blocked"
        ):
            stage = "route_guidance_blocked"
            actions = [
                "Resolve blocked model route guidance before widening validation.",
                *[str(item) for item in route_guidance.get("recommended_actions", [])],
                *actions,
            ]
        if stage == "ready_for_small_real_task_validation" and _promotion_risks_exceed_threshold(
            promotion_release_risks
        ):
            stage = "candidate_promotion_risk_blocked"
            actions = [
                "Resolve release-blocking candidate promotions before validation.",
                "Use `asteria promotions list`, then approve, retry, reject, or discard unresolved candidates.",
                *actions,
            ]
        plugin_risks = _plugin_risks(self.root, self.validator)
        if stage == "ready_for_small_real_task_validation" and plugin_risks["blocked"]:
            stage = "plugin_manifests_blocked"
            actions = [
                *plugin_risks["actions"],
                *actions,
            ]
        policy = self._policy()
        env_capabilities = {
            "strong_model_configured": bool(route_environment.get("strong", {}).get("configured")),
            "medium_model_configured": bool(route_environment.get("medium", {}).get("configured")),
            "real_model_available": bool(gate.get("ok")),
            "provider_streaming_available": _provider_streaming_available(route_environment),
        }
        resolver = FlagResolver.from_policy(policy, env_capabilities)
        flag_results = resolver.resolve_all()
        feature_flags = {n: v for n, v in flag_results.items()}
        capability_flags = {n: c.to_dict() for n, c in resolver.capabilities.items()}

        progress_metrics = runtime_progress_metrics(self.root, self.validator)
        validation_matrix = runtime_validation_matrix(self.root, progress_metrics)
        recovery_pressure = recovery_pressure_report(self.root, self.validator)
        context_pressure_summary = _context_pressure_summary(self.root)
        v0_2_rolling_validation = _latest_v0_2_rolling_validation(self.root)
        rolling_status = str(v0_2_rolling_validation.get("status") or "")
        if rolling_status in {"needs_more_samples", "needs_evidence"}:
            actions = [
                *actions,
                *[str(item) for item in v0_2_rolling_validation.get("next_actions", [])],
            ]
        elif not rolling_status:
            actions = [
                *actions,
                "Export `asteria evidence-bundle --json` after scoped tasks to create v0.2 rolling validation evidence.",
            ]

        return GateStatusResult(
            root=self.root,
            stage=stage,
            gate_report=gate,
            validation_report=validation,
            core_report=core,
            route_environment=route_environment,
            route_guidance=route_guidance,
            route_table=route_table,
            model_call_contract=model_call_contract,
            latest_observation_plan=latest_observation_plan,
            latest_real_provider_matrix=latest_matrix,
            promotion_release_risks=promotion_release_risks,
            plugin_risks=plugin_risks,
            runtime_progress_metrics=progress_metrics,
            runtime_validation_matrix=validation_matrix,
            v0_2_rolling_validation=v0_2_rolling_validation,
            recovery_pressure=recovery_pressure,
            context_pressure_summary=context_pressure_summary,
            validation_recommendation=_validation_recommendation(self.root),
            feature_flags=feature_flags,
            capability_flags=capability_flags,
            evidence_sources=_evidence_sources(
                gate_path if gate else None,
                validation_path,
                core_path,
            ),
            next_actions=actions,
        )

    def _policy(self) -> dict[str, Any]:
        agent_dir = self.root / ".asteria"
        if not (agent_dir / "policies.json").exists():
            return {}
        return load_policy_config(agent_dir, self.validator)

    def _stage(
        self,
        gate: dict[str, Any],
        validation: dict[str, Any],
        core: dict[str, Any],
    ) -> tuple[str, list[str]]:
        if not gate:
            return (
                "missing_real_model_gate",
                [
                    "Run `python scripts/real_model_gate.py --summary-json .asteria/model/real_model_gate_report.json`."
                ],
            )
        if not gate.get("ok"):
            return ("real_model_gate_failed", list(gate.get("recommended_actions") or []))
        if not validation:
            return (
                "ready_for_validation_suite",
                [
                    "Run `python scripts/real_model_acceptance.py --suite validation --summary-json .asteria/verification/real_model_acceptance_validation.json`."
                ],
            )
        if not validation.get("ok") or validation.get("validation_ready") is not True:
            actions = _validation_failure_next_actions(validation, self.validator)
            return (
                "validation_suite_failed",
                actions
                or ["Inspect validation suite evidence; do not proceed to core acceptance yet."],
            )
        if not core:
            return (
                "ready_for_core_acceptance",
                [
                    "Run `python scripts/real_model_acceptance.py --suite core --summary-json .asteria/verification/real_model_acceptance_core.json`."
                ],
            )
        if not core.get("ok"):
            return ("core_acceptance_failed", ["Repair core acceptance failures before release."])
        return (
            "ready_for_small_real_task_validation",
            [
                "Start small real-task validation with `--max-iterations 3 --max-tasks-per-iteration 1 --no-research`.",
                "Stop and collect evidence if cost status reaches near_limit or a merge/protected-path risk appears.",
            ],
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _latest_acceptance_report(self, suite: str) -> tuple[dict[str, Any], Path | None]:
        verification_dir = self.root / ".asteria" / "verification"
        if not verification_dir.exists():
            return {}, None
        canonical = verification_dir / f"real_model_acceptance_{suite}.json"
        canonical_report = self._read_json(canonical)
        if _matches_acceptance_suite(canonical_report, suite) and canonical_report.get("ok"):
            return canonical_report, canonical
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        for path in verification_dir.glob(f"real_model_acceptance_{suite}*.json"):
            report = self._read_json(path)
            if _matches_acceptance_suite(report, suite):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    modified = 0.0
                candidates.append((modified, path, report))
        if not candidates:
            return {}, None
        _modified, path, report = max(candidates, key=lambda item: (item[0], item[1].name))
        if suite == "validation":
            report = _with_acceptance_repair_closure(report, path, verification_dir)
        return report, path


def _validation_task_limits() -> dict[str, object]:
    return {
        "max_iterations": 3,
        "max_tasks_per_iteration": 1,
        "max_repairs": 1,
        "max_replans": 1,
        "recommended_run_flags": [
            "--max-iterations 3",
            "--max-tasks-per-iteration 1",
            "--no-research",
        ],
        "stop_conditions": [
            "cost_status near_limit or hard_stop",
            "merge gate promotion risk",
            "protected path risk",
            "session cannot resume",
        ],
    }


def _validation_failure_next_actions(
    validation: dict[str, Any],
    validator: SchemaValidator,
) -> list[str]:
    actions: list[str] = []
    for scenario in validation.get("scenarios") or []:
        if not isinstance(scenario, dict) or scenario.get("ok"):
            continue
        workspace = scenario.get("workspace")
        if not workspace:
            continue
        run_id = (
            ((scenario.get("summary") or {}).get("run_id"))
            if isinstance(scenario.get("summary"), dict)
            else None
        )
        run_dir = _scenario_run_dir(Path(str(workspace)), str(run_id) if run_id else None)
        execution = latest_agent_loop_execution_result(run_dir, validator) or {}
        command = str(execution.get("recommended_command") or "")
        if not command:
            decision = latest_agent_loop_decision(run_dir, validator) or {}
            command = recommended_command_for_next_action(decision.get("next_action") or {}) or ""
        if command:
            actions.append(
                f"Run `asteria {command} --root {workspace}` for failed scenario "
                f"{scenario.get('scenario', 'unknown')}."
            )
        else:
            actions.append(
                f"Inspect failed scenario {scenario.get('scenario', 'unknown')} evidence at {workspace}."
            )
    return actions[:5]


def _scenario_run_dir(workspace: Path, run_id: str | None) -> Path | None:
    runs_dir = workspace / ".asteria" / "runs"
    if run_id:
        return runs_dir / run_id
    if not runs_dir.exists():
        return None
    run_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    return run_dirs[-1] if run_dirs else None


def _route_environment() -> dict[str, Any]:
    return route_environment_for_tiers(("strong", "medium"))


def _route_table() -> dict[str, Any]:
    # Informational-only view of every tier's resolved route (provider/model/selection reason) plus
    # which tiers silently return canned output. Deliberately SEPARATE from _route_environment(),
    # which drives gate readiness: the cheap tier is allowed to be fake/offline, so it must never
    # count against readiness — this table exposes it honestly without blocking the gate.
    tiers = ("strong", "medium", "cheap")
    routes = {tier: route_diagnostic_for_tier(tier).to_dict() for tier in tiers}
    offline_tiers = [
        tier for tier, route in routes.items() if str(route.get("provider")) in {"fake", "offline"}
    ]
    return {
        "tiers": routes,
        "offline_tiers": offline_tiers,
        # True when some (but not all) tiers are offline: those silently return canned output while
        # real providers are configured elsewhere — the exact footgun to surface.
        "silently_offline": 0 < len(offline_tiers) < len(tiers),
    }


def _provider_streaming_available(route_environment: dict[str, Any]) -> bool:
    for tier in ("strong", "medium"):
        raw_route = route_environment.get(tier)
        route = raw_route if isinstance(raw_route, dict) else {}
        raw_streaming = route.get("streaming")
        streaming = raw_streaming if isinstance(raw_streaming, dict) else {}
        if streaming.get("enabled") is not True:
            return False
    return True


def _matches_acceptance_suite(report: dict[str, Any], suite: str) -> bool:
    if not report:
        return False
    report_suite = report.get("suite")
    if report_suite is None:
        return True
    if str(report_suite) != suite:
        return False
    return _has_complete_acceptance_suite(report, suite)


def _with_acceptance_repair_closure(
    report: dict[str, Any],
    report_path: Path,
    verification_dir: Path,
) -> dict[str, Any]:
    if report.get("ok") or not report.get("scenarios"):
        return report
    failed = [
        str(item.get("scenario") or "")
        for item in report.get("scenarios") or []
        if isinstance(item, dict) and item.get("ok") is not True and item.get("scenario")
    ]
    if not failed:
        return report
    try:
        report_mtime = report_path.stat().st_mtime
    except OSError:
        report_mtime = 0.0
    closed: dict[str, str] = {}
    for path in verification_dir.glob("real_model_acceptance_validation*.json"):
        if path == report_path:
            continue
        try:
            if path.stat().st_mtime <= report_mtime:
                continue
        except OSError:
            continue
        candidate = _read_json_file(path)
        if candidate.get("ok") is not True:
            continue
        for scenario in candidate.get("scenarios") or []:
            if not isinstance(scenario, dict) or scenario.get("ok") is not True:
                continue
            name = str(scenario.get("scenario") or "")
            if name in failed:
                closed[name] = path.name
    remaining = [name for name in failed if name not in closed]
    if remaining:
        return report
    repaired = dict(report)
    aggregate = dict(repaired.get("aggregate") or {})
    failed_count = int(aggregate.get("failed") or len(failed))
    closed_count = len(closed)
    aggregate["failed"] = max(0, failed_count - closed_count)
    aggregate["passed"] = int(aggregate.get("passed") or 0) + min(failed_count, closed_count)
    repaired["aggregate"] = aggregate
    repaired["ok"] = aggregate["failed"] == 0
    repaired["complete"] = repaired["ok"]
    repaired["validation_ready"] = repaired["ok"]
    repaired["repair_closure"] = {
        "rerun_ok": True,
        "closed_failures": sorted(closed),
        "remaining_failures": remaining,
        "evidence_files": {name: closed[name] for name in sorted(closed)},
    }
    return repaired


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _has_complete_acceptance_suite(report: dict[str, Any], suite: str) -> bool:
    if suite != "validation":
        return True
    expected = set(REAL_MODEL_ACCEPTANCE_SUITES.get(suite, ()))
    if not expected:
        return True
    requested = {str(item) for item in report.get("requested_scenarios") or [] if str(item)}
    if requested and not expected.issubset(requested):
        return False
    raw_metadata = report.get("scenario_metadata")
    if isinstance(raw_metadata, list):
        observed = {
            str(item.get("scenario") or "") for item in raw_metadata if isinstance(item, dict)
        }
        return expected.issubset(observed)
    aggregate = report.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    return int(aggregate.get("total") or 0) >= len(expected)


def _latest_observation_plan(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    agent_dir = root / ".asteria"
    try:
        run_id = RunStore(agent_dir, validator).current_session_id()
    except RuntimeError:
        run_id = None
    if not run_id:
        return {}
    path = agent_dir / "runs" / run_id / "observation_plans.jsonl"
    if not path.exists():
        return {}
    plans = JsonlStore(validator).read_all(path, "observation_plan")
    if not plans:
        return {}
    latest = plans[-1]
    return {
        "observation_plan_id": latest.get("observation_plan_id"),
        "run_id": latest.get("run_id"),
        "task_id": latest.get("task_id"),
        "trigger": latest.get("trigger"),
        "failed_observation_count": latest.get("failed_observation_count"),
        "recommended_route": latest.get("recommended_route"),
        "reason": latest.get("reason"),
        "evidence_refs": list(latest.get("evidence_refs") or [])[:5],
        "created_at": latest.get("created_at"),
    }


def _current_release_observation_plan(
    plan: dict[str, Any],
    validation_path: Path | None,
    core_path: Path | None,
) -> dict[str, Any]:
    if not plan:
        return {}
    created_at = _parse_iso_datetime(str(plan.get("created_at") or ""))
    if created_at is None:
        return plan
    evidence_times = [
        datetime.fromtimestamp(path.stat().st_mtime, tz=created_at.tzinfo)
        for path in (validation_path, core_path)
        if path is not None and path.exists()
    ]
    if evidence_times and created_at < max(evidence_times):
        return {}
    return plan


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _evidence_sources(
    gate_path: Path | None,
    validation_path: Path | None,
    core_path: Path | None,
) -> dict[str, str]:
    sources: dict[str, str] = {}
    if gate_path is not None:
        sources["real_model_gate"] = str(gate_path)
    if validation_path is not None:
        sources["validation_suite"] = str(validation_path)
    if core_path is not None:
        sources["core_acceptance"] = str(core_path)
    return sources


def _context_pressure_summary(root: Path) -> dict[str, Any]:
    runs_dir = root / ".asteria" / "runs"
    if not runs_dir.exists():
        return {}
    max_tokens = 0
    max_ratio = 0.0
    sections: dict[str, int] = {}
    duplicate_hashes: list[str] = []
    latest_subagent_snapshot: dict[str, Any] = {}
    latest_subagent_created = ""
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        cost_path = run_dir / "cost_report.json"
        if cost_path.exists():
            try:
                cost = json.loads(cost_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cost = {}
            max_tokens = max(max_tokens, int(cost.get("max_context_estimated_tokens") or 0))
            max_ratio = max(max_ratio, float(cost.get("context_window_ratio") or 0.0))
            raw_sections = cost.get("max_context_sections") or cost.get("latest_context_sections")
            if isinstance(raw_sections, dict):
                for key, value in raw_sections.items():
                    sections[str(key)] = max(sections.get(str(key), 0), int(value or 0))
            raw_hashes = cost.get("context_duplicate_content_hashes")
            if isinstance(raw_hashes, list):
                duplicate_hashes.extend(str(item) for item in raw_hashes)
        snapshots_path = run_dir / "context_budget_snapshots.jsonl"
        if snapshots_path.exists():
            try:
                snapshots = JsonlStore().read_all(snapshots_path, None)
            except (OSError, ValueError):
                snapshots = []
            for item in snapshots:
                if str(item.get("scope") or "") != "subagent_child":
                    continue
                max_tokens = max(max_tokens, int(item.get("estimated_tokens") or 0))
                max_ratio = max(max_ratio, float(item.get("context_window_ratio") or 0.0))
                raw_sections = item.get("sections")
                if isinstance(raw_sections, dict):
                    for key, value in raw_sections.items():
                        sections[str(key)] = max(sections.get(str(key), 0), int(value or 0))
                raw_hashes = item.get("duplicate_content_hashes")
                if isinstance(raw_hashes, list):
                    duplicate_hashes.extend(str(entry) for entry in raw_hashes)
                created = str(item.get("created_at") or "")
                if not latest_subagent_snapshot or created >= latest_subagent_created:
                    latest_subagent_snapshot = item
                    latest_subagent_created = created
    subagent_summary = {}
    if latest_subagent_snapshot:
        subagent_summary = {
            "snapshot_id": latest_subagent_snapshot.get("snapshot_id"),
            "task_id": latest_subagent_snapshot.get("task_id"),
            "runtime_profile_id": latest_subagent_snapshot.get("runtime_profile_id"),
            "parent_worker_invocation_id": latest_subagent_snapshot.get(
                "parent_worker_invocation_id"
            ),
            "estimated_tokens": int(latest_subagent_snapshot.get("estimated_tokens") or 0),
            "context_window_ratio": float(
                latest_subagent_snapshot.get("context_window_ratio") or 0.0
            ),
            "pressure_status": latest_subagent_snapshot.get("pressure_status"),
            "compact_boundary": latest_subagent_snapshot.get("compact_boundary") or {},
            "duplicate_estimated_tokens": int(
                latest_subagent_snapshot.get("duplicate_estimated_tokens") or 0
            ),
            "duplicate_ref_count": int(latest_subagent_snapshot.get("duplicate_ref_count") or 0),
        }
    return {
        "max_context_estimated_tokens": max_tokens,
        "max_context_window_ratio": max_ratio,
        "sections": dict(sorted(sections.items())),
        "duplicate_content_hashes": list(dict.fromkeys(duplicate_hashes))[:20],
        "subagent_child_context": subagent_summary,
        "status": "observed" if max_tokens > 0 else "no_current_context_estimates",
    }


def _route_guidance(root: Path) -> dict[str, Any]:
    validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
    return CapabilityFeedbackAdvisor(validator).route_guidance(root / ".asteria")


def _latest_v0_2_rolling_validation(root: Path) -> dict[str, Any]:
    bundle_dir = root / ".asteria" / "evidence_bundles"
    if not bundle_dir.exists():
        return {}
    manifests = sorted(bundle_dir.glob("*.manifest.json"), reverse=True)
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = manifest.get("v0_2_rolling_validation")
        if not isinstance(raw, dict):
            continue
        coverage = raw.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        next_actions = [str(item) for item in raw.get("next_actions") or [] if item]
        missing = [str(name) for name, covered in coverage.items() if name and covered is not True]
        status = str(raw.get("status") or "")
        sample_count = int(raw.get("sample_count") or 0)
        required_range = raw.get("required_sample_range")
        required_range = (
            required_range if isinstance(required_range, dict) else {"min": 3, "max": 5}
        )
        return {
            "status": status,
            "sample_count": sample_count,
            "required_sample_range": required_range,
            "coverage": {
                "route": bool(coverage.get("route")),
                "context": bool(coverage.get("context")),
                "capability": bool(coverage.get("capability")),
                "loop": bool(coverage.get("loop")),
                "worker": bool(coverage.get("worker")),
            },
            "missing_evidence_categories": missing,
            "next_actions": next_actions,
            "evidence_source": str(manifest_path),
        }
    return {}


def _release_evidence_route_guidance(
    guidance: dict[str, Any],
    gate: dict[str, Any],
    validation: dict[str, Any],
    core: dict[str, Any],
) -> dict[str, Any]:
    if guidance.get("status") not in {"blocked", "review"} or not _release_route_evidence_is_fresh(
        gate, validation, core
    ):
        return guidance
    raw_blocking = guidance.get("blocking") or []
    blocking = [item for item in raw_blocking if isinstance(item, dict)]
    raw_review = guidance.get("review") or []
    review = [item for item in raw_review if isinstance(item, dict)]
    strategy = guidance.get("provider_route_strategy")
    strategy = strategy if isinstance(strategy, dict) else {}
    retained: list[dict[str, Any]] = []
    demoted_blocking: list[dict[str, Any]] = []
    for item in blocking:
        if _is_superseded_route_guidance_item(item, gate, validation, strategy):
            demoted_blocking.append(
                {**item, "severity": 2, "release_evidence_status": "superseded"}
            )
        else:
            retained.append(item)
    active_review: list[dict[str, Any]] = []
    superseded_review: list[dict[str, Any]] = []
    for item in review:
        if _is_superseded_route_guidance_item(item, gate, validation, strategy):
            superseded_review.append(
                {**item, "severity": 1, "release_evidence_status": "superseded"}
            )
        else:
            active_review.append(item)
    if not demoted_blocking and not superseded_review:
        return guidance
    status = "blocked" if retained else "review" if active_review else "healthy"
    actions = _product_route_guidance_actions(
        blocking=retained,
        review=active_review,
        strategy=strategy,
        fallback=list(guidance.get("recommended_actions") or []),
    )
    return {
        **guidance,
        "status": status,
        "blocking": retained,
        "review": active_review,
        "active_review": active_review,
        "superseded_review": [*superseded_review, *demoted_blocking],
        "historical_review": [*superseded_review, *demoted_blocking],
        "release_evidence_override": {
            "applied": True,
            "demoted_blockers": len(demoted_blocking),
            "superseded_review": len(superseded_review),
            "reason": "Latest real-model gate and acceptance evidence supersede stale route guidance blockers.",
        },
        "recommended_actions": actions,
    }


def _product_route_guidance_actions(
    *,
    blocking: list[dict[str, Any]],
    review: list[dict[str, Any]],
    strategy: dict[str, Any],
    fallback: list[Any],
) -> list[str]:
    if blocking:
        actions: list[str] = []
        if any(
            item.get("recommended_action") == "review_real_provider_matrix_before_scaling"
            for item in blocking
        ):
            actions.append(
                "Rerun or repair failed real-provider matrix task_kind/route evidence before widening validation."
            )
        if any(
            item.get("recommended_action") == "block_validation_until_strong_goal_spec_stable"
            for item in blocking
        ):
            actions.append(
                "Run `asteria model-check --tier strong --json`, then rerun a small real-task validation sample."
            )
        if not actions:
            actions.append(
                "Run `asteria capability-report` and repair the active blocked route evidence."
            )
        return actions
    if review:
        actions = []
        if (
            any(
                item.get("recommended_action") == "retry_or_downgrade_strong_goal_spec"
                for item in review
            )
            or strategy.get("decision") == "retry_or_downgrade"
        ):
            actions.append(
                "Keep strong goal_spec on retry/downgrade guard; rerun one small validation sample before widening."
            )
        if any(
            item.get("recommended_action") == "review_real_provider_matrix_before_scaling"
            for item in review
        ):
            actions.append(
                "Review real-provider matrix task_kind/route failures before increasing validation batch size."
            )
        if not actions:
            purposes = sorted(
                {str(item.get("purpose") or "unknown") for item in review if isinstance(item, dict)}
            )
            joined = ", ".join(purposes[:3]) if purposes else "affected routes"
            actions.append(f"Review active route evidence for {joined} before widening scope.")
        return actions
    if fallback:
        return [str(fallback[0])]
    return ["Fresh release and route evidence supersede stale route guidance noise."]


def _release_route_evidence_is_fresh(
    gate: dict[str, Any],
    validation: dict[str, Any],
    core: dict[str, Any],
) -> bool:
    if not gate.get("ok") or not core.get("ok"):
        return False
    if not _gate_model_call_run_id(gate):
        return False
    if validation.get("ok") is not True or validation.get("validation_ready") is not True:
        return False
    aggregate = validation.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    route = aggregate.get("route_evidence")
    route = route if isinstance(route, dict) else {}
    return route.get("strong_used") is True and route.get("medium_used") is True


def _is_superseded_route_guidance_item(
    item: dict[str, Any],
    gate: dict[str, Any],
    validation: dict[str, Any],
    strategy: dict[str, Any] | None = None,
) -> bool:
    strategy = strategy or {}
    action = str(item.get("recommended_action") or "")
    provider = str(item.get("provider") or "").lower()
    if provider in {"fake", "offline"}:
        return True
    if (
        strategy.get("decision") == "continue_primary"
        and item.get("model_tier") == "strong"
        and _route_model_names_match(str(item.get("model") or ""), str(strategy.get("model") or ""))
    ):
        return True
    if action == "block_validation_until_strong_goal_spec_stable":
        routes = gate.get("routes")
        routes = routes if isinstance(routes, dict) else {}
        strong_route = routes.get("strong")
        strong_route = strong_route if isinstance(strong_route, dict) else {}
        gate_model = str(strong_route.get("model") or "")
        blocked_model = str(item.get("model") or "")
        return bool(gate_model and blocked_model and gate_model != blocked_model)
    if action == "review_worker_route_before_scaling":
        aggregate = validation.get("aggregate")
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        route = aggregate.get("route_evidence")
        route = route if isinstance(route, dict) else {}
        if item.get("model_tier") == "medium":
            return route.get("medium_used") is True
        if item.get("model_tier") == "strong":
            return route.get("strong_used") is True
    return False


def _route_model_names_match(left: str, right: str) -> bool:
    left = left.strip()
    right = right.strip()
    if left == right:
        return True
    glm5_aliases = {"glm-5", "glm-5.1"}
    return left in glm5_aliases and right in glm5_aliases


def _model_call_contract(
    root: Path,
    validator: SchemaValidator,
    gate_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calls, evidence_scope = _model_call_contract_calls(root, validator, gate_report or {})
    if not calls:
        return {
            "status": "unknown",
            "checked_calls": 0,
            "evidence_scope": evidence_scope,
            "summary": "No recent real-provider model_calls.jsonl evidence was found.",
            "recommended_actions": [
                "Run model-check or a small real-provider validation task to collect model call contract evidence."
            ],
            "violations": [],
        }
    violations = []
    for call in calls:
        missing = []
        if not isinstance(call.get("agent_role_contract"), dict):
            missing.append("agent_role_contract")
        if not isinstance(call.get("deadline_ms"), int):
            missing.append("deadline_ms")
        streaming = call.get("streaming")
        if not isinstance(streaming, dict):
            missing.append("streaming")
        elif streaming.get("deadline_ms") is None and streaming.get("idle_timeout_ms") is None:
            missing.append("streaming.deadline_or_idle_timeout")
        if missing:
            violations.append(
                {
                    "model_call_id": call.get("model_call_id"),
                    "run_id": call.get("run_id"),
                    "purpose": call.get("purpose"),
                    "model_provider": call.get("model_provider"),
                    "model_name": call.get("model_name"),
                    "missing": missing,
                    "path": str(call.get("_path")),
                }
            )
    status = "blocked" if violations else "healthy"
    return {
        "status": status,
        "checked_calls": len(calls),
        "violation_count": len(violations),
        "evidence_scope": evidence_scope,
        "summary": (
            "Release evidence model calls include role contract, deadline, and streaming telemetry."
            if not violations
            else "Release evidence model calls are missing role contract, deadline, or streaming telemetry."
        ),
        "recommended_actions": []
        if not violations
        else [
            "Rerun the affected real-provider checks after the AgentRoleContract deadline changes.",
            "Inspect model_calls.jsonl entries listed in model_call_contract.violations.",
        ],
        "violations": violations[:10],
    }


def _model_call_contract_calls(
    root: Path,
    validator: SchemaValidator,
    gate_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    gate_run_id = _gate_model_call_run_id(gate_report)
    if gate_run_id:
        gate_calls = _model_calls_for_run(root, validator, gate_run_id)
        if gate_calls:
            return gate_calls, "real_model_gate_run"
    calls: list[dict[str, Any]] = []
    for run_dir in _run_dirs(root):
        path = run_dir / "model_calls.jsonl"
        if not path.exists():
            continue
        for call in JsonlStore(validator).read_all(path, "model_call"):
            if str(call.get("model_provider") or "").lower() == "fake":
                continue
            item = dict(call)
            item["_path"] = path
            calls.append(item)
    calls = sorted(calls, key=lambda item: str(item.get("created_at") or ""))[-50:]
    return calls, "recent_real_provider_calls"


def _gate_model_call_run_id(gate_report: dict[str, Any]) -> str | None:
    if not gate_report.get("ok"):
        return None
    raw_summary = gate_report.get("model_call_summary")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    run_id = summary.get("run_id")
    return str(run_id) if run_id else None


def _model_calls_for_run(
    root: Path,
    validator: SchemaValidator,
    run_id: str,
) -> list[dict[str, Any]]:
    path = root / ".asteria" / "runs" / run_id / "model_calls.jsonl"
    if not path.exists():
        return []
    calls: list[dict[str, Any]] = []
    for call in JsonlStore(validator).read_all(path, "model_call"):
        if str(call.get("model_provider") or "").lower() == "fake":
            continue
        item = dict(call)
        item["_path"] = path
        calls.append(item)
    return calls


def _real_provider_matrix_next_actions(matrix: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    route = str(matrix.get("latest_route") or "unknown")
    task_kind = str(matrix.get("latest_task_kind") or "unknown")
    case = str(matrix.get("latest_case") or "unknown")
    summary_path = str(matrix.get("summary_path") or "matrix_summary.json")
    latest_classification = str(matrix.get("latest_retry_classification") or "")
    if matrix.get("ok") is False:
        if latest_classification == "provider_transient":
            route_command = (
                "Run `asteria model-check --tier medium --json`, then rerun the targeted "
                "real-provider matrix case after provider health recovers."
            )
        else:
            route_command = {
                "repair": "Run the failed matrix case through `asteria debug` or rerun `asteria real-model-smoke --matrix p0 --matrix-case <case>` after fixing verification.",
                "replan": "Run `asteria replan` for the failed matrix case contract, then rerun the targeted matrix case.",
                "ask": "Resolve the permission or scope question before rerunning the targeted matrix case.",
                "stop": "Stop widening validation until repeated no-new-evidence is investigated.",
            }.get(
                route,
                "Inspect the failed matrix case and rerun the targeted matrix case after repair.",
            )
        actions.extend(
            [
                (
                    "Latest real-provider P0 matrix failed: "
                    f"{case} requires {route} for task_kind={task_kind}; inspect {summary_path}."
                ),
                route_command,
            ]
        )
    actions.extend(_real_provider_matrix_trend_next_actions(matrix))
    return list(dict.fromkeys(actions))


def _real_provider_matrix_trend_next_actions(matrix: dict[str, Any]) -> list[str]:
    trend = matrix.get("trend")
    trend = trend if isinstance(trend, dict) else {}
    cases = trend.get("cases")
    cases = cases if isinstance(cases, dict) else {}
    bugfix = cases.get("single_file_bugfix")
    bugfix = bugfix if isinstance(bugfix, dict) else {}
    classifications = bugfix.get("retry_classifications")
    classifications = classifications if isinstance(classifications, dict) else {}
    latest_classification = str(bugfix.get("latest_retry_classification") or "")
    summary_path = str(matrix.get("summary_path") or "matrix_summary.json")
    actions: list[str] = []
    if latest_classification == "provider_transient" or (
        not latest_classification and classifications.get("provider_transient")
    ):
        actions.append(
            "Treat single_file_bugfix provider transient evidence as route/provider health; "
            f"inspect failed model call types in {summary_path} before spending repair attempts."
        )
    if latest_classification == "extra_execution_without_repair" or (
        not latest_classification and classifications.get("extra_execution_without_repair")
    ):
        actions.append(
            "Review single_file_bugfix prompt/schema for extra medium execution without repair; "
            f"compare task_execution model calls in {summary_path}."
        )
    if latest_classification == "fast_path_mismatch" or (
        not latest_classification and classifications.get("fast_path_mismatch")
    ):
        actions.append(
            "Tighten single_file_bugfix fast-path/context target detection before widening this case."
        )
    if latest_classification in {"repair_loop", "failed_after_repair"} or (
        not latest_classification
        and (classifications.get("repair_loop") or classifications.get("failed_after_repair"))
    ):
        actions.append(
            "Inspect single_file_bugfix planner/tool-contract evidence; recent matrix trend still shows repair-loop behavior."
        )
    if int(float(bugfix.get("strong_model_calls_max") or 0)) > 0:
        actions.append(
            "Investigate why single_file_bugfix used strong model calls in recent matrix samples."
        )
    warnings = [str(item) for item in trend.get("warnings") or [] if item]
    if warnings:
        actions.append("Review real-provider matrix trend warnings: " + "; ".join(warnings[:2]))
    return actions


def _promotion_release_risks(root: Path, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
    evidence = runtime_os_release_evidence(_run_dirs(root), JsonlStore(validator).read_all)
    risk_policy = _promotion_risk_policy(policy or {})
    return {
        "total": int(evidence.get("candidate_promotions") or 0),
        "pending": int(evidence.get("candidate_promotions_pending") or 0),
        "blocked": int(evidence.get("candidate_promotions_blocked") or 0),
        "promoted": int(evidence.get("candidate_promotions_promoted") or 0),
        "risk_policy": risk_policy,
        "release_blocking_threshold": max(
            int(risk_policy["max_pending_release_promotions"]),
            int(risk_policy["max_blocked_release_promotions"]),
        ),
        "release_blocking_statuses": list(risk_policy["release_blocking_statuses"]),
    }


def _promotion_risk_policy(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("promotion")
    promotion = raw if isinstance(raw, dict) else {}
    return {
        "manual_approval_default": bool(promotion.get("manual_approval_default", False)),
        "release_blocking_statuses": list(
            promotion.get("release_blocking_statuses")
            or [
                "queued",
                "pending_manual_approval",
                "approved",
                "blocked",
                "promotion_failed",
            ]
        ),
        "max_pending_release_promotions": int(promotion.get("max_pending_release_promotions", 0)),
        "max_blocked_release_promotions": int(promotion.get("max_blocked_release_promotions", 0)),
    }


def _promotion_risks_exceed_threshold(risks: dict[str, Any]) -> bool:
    raw_policy = risks.get("risk_policy")
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    max_pending = int(policy.get("max_pending_release_promotions", 0))
    max_blocked = int(policy.get("max_blocked_release_promotions", 0))
    return int(risks.get("pending", 0)) > max_pending or int(risks.get("blocked", 0)) > max_blocked


def _run_dirs(root: Path) -> list[Path]:
    runs_dir = root / ".asteria" / "runs"
    return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []


def _validation_recommendation(root: Path) -> dict[str, Any]:
    changed_files = _changed_files(root)
    return _validation_recommendation_for_changed_files(changed_files)


def _changed_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    files = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        files.append(path.replace("\\", "/"))
    return files


def _validation_recommendation_for_changed_files(changed_files: list[str]) -> dict[str, Any]:
    if not changed_files:
        return {
            "level": "none",
            "reason": "No git changes detected or git status unavailable.",
            "changed_file_count": 0,
            "command": "asteria gate-status --json",
        }
    source_changes = [
        path
        for path in changed_files
        if path.startswith(("src/", "tests/", "schemas/", "scripts/"))
    ]
    runtime_changes = [
        path
        for path in changed_files
        if path.startswith(
            (
                "src/asteria_runtime/core/",
                "src/asteria_runtime/commands/",
                "src/asteria_runtime/acceptance/",
                "src/asteria_runtime/models/",
            )
        )
    ]
    docs_only = all(path.startswith("docs/") or path.endswith(".md") for path in changed_files)
    if docs_only:
        return {
            "level": "targeted",
            "reason": "Only documentation changed.",
            "changed_file_count": len(changed_files),
            "command": "ruff check .",
        }
    governance_changes = [
        path
        for path in changed_files
        if path.startswith(("schemas/", "templates/"))
        or "plugin_manifest" in path
        or "runtime_hook" in path
        or "policy_config" in path
        or "policies.default" in path
    ]
    if governance_changes:
        return {
            "level": "full_validation_core",
            "reason": "Schema, policy, or hook/plugin governance files changed.",
            "changed_file_count": len(changed_files),
            "governance_changes": governance_changes,
            "command": (
                "ruff check . && mypy src && pytest -q && "
                "asteria package-check --root . --json && "
                "asteria /acceptance-gate --suite core"
            ),
        }
    if len(changed_files) >= 12 or len(runtime_changes) >= 4:
        return {
            "level": "full_validation_core",
            "reason": "Broad Runtime OS changes detected.",
            "changed_file_count": len(changed_files),
            "command": (
                "ruff check . && mypy src && pytest -q && "
                "asteria real-model-gate && asteria real-model-acceptance --suite validation && "
                "asteria /acceptance-gate --suite core"
            ),
        }
    if source_changes:
        return {
            "level": "core_subset",
            "reason": "Runtime source or test files changed.",
            "changed_file_count": len(changed_files),
            "command": "ruff check . && mypy src && pytest -q && asteria /acceptance-gate --suite core --min-scenarios 6",
        }
    return {
        "level": "targeted",
        "reason": "Small non-runtime change detected.",
        "changed_file_count": len(changed_files),
        "command": "ruff check . && pytest -q",
    }


def _plugin_risks(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    try:
        summary = plugin_control_summary(root, validator)
    except (FileNotFoundError, OSError, ValueError):
        return {"blocked": False, "warnings": [], "actions": [], "plugin_control": {}}
    if not summary.get("initialized", False):
        return {"blocked": False, "warnings": [], "actions": [], "plugin_control": summary}
    blocked_ids = [
        str(p.get("plugin_id", "?"))
        for p in summary.get("plugins", [])
        if p.get("status") == "blocked"
    ]
    warnings = list(summary.get("warnings") or [])
    actions: list[str] = []
    if blocked_ids:
        actions.append(f"Blocked plugin manifests prevent release: {', '.join(blocked_ids)}.")
        actions.append("Run steria plugins doctor --json and fix or disable blocked manifests.")
    if not summary.get("ok", True):
        actions.append("Plugin control surface reports issues; resolve before release.")
    return {
        "blocked": len(blocked_ids) > 0,
        "blocked_manifests": blocked_ids,
        "warnings": warnings,
        "actions": actions,
        "plugin_control": summary,
    }
