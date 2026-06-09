from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from asteria_runtime.acceptance.runtime_os_catalog import (
    RUNTIME_OS_CAPABILITIES,
    RuntimeOSCapability,
)


@dataclass(frozen=True)
class RuntimeOSGateEvaluation:
    required: bool
    status: str
    covered_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "status": self.status,
            "covered_capabilities": self.covered_capabilities,
            "missing_capabilities": self.missing_capabilities,
            "missing_evidence": self.missing_evidence,
        }


class RuntimeOSGateEvaluator:
    def __init__(
        self,
        capabilities: Sequence[RuntimeOSCapability] = RUNTIME_OS_CAPABILITIES,
    ) -> None:
        self.capabilities = list(capabilities)
        self.capability_by_name = {item.capability: item for item in self.capabilities}

    def evaluate(
        self,
        report: dict[str, Any],
        scenarios: Sequence[dict[str, Any]],
        *,
        required: bool,
    ) -> RuntimeOSGateEvaluation:
        del report
        covered: set[str] = set()
        missing_evidence: list[str] = []
        suite_evidence: dict[str, bool] = {}
        for required_capability in self.capabilities:
            for key in required_capability.suite_evidence:
                suite_evidence.setdefault(key, False)

        for scenario in scenarios:
            if not scenario.get("ok"):
                continue
            summary = _dict(scenario.get("summary"))
            runtime = _dict(summary.get("runtime_os"))
            if not runtime:
                continue
            capability_name = str(
                runtime.get("capability")
                or scenario.get("capability")
                or scenario.get("scenario")
                or ""
            )
            runtime_capability = self.capability_by_name.get(capability_name)
            if runtime_capability is None:
                continue
            covered.add(runtime_capability.capability)
            evidence = _dict(runtime.get("evidence"))
            scenario_name = str(scenario.get("scenario") or runtime_capability.scenario)
            for key in runtime_capability.required_evidence:
                if not evidence.get(key):
                    missing_evidence.append(f"{scenario_name}: missing {key}")
            for key in runtime_capability.suite_evidence:
                if evidence.get(key):
                    suite_evidence[key] = True
            for key in runtime_capability.special_evidence:
                if not evidence.get(key):
                    missing_evidence.append(self._special_missing_message(scenario_name, key))

        if covered:
            for key, present in suite_evidence.items():
                if not present:
                    missing_evidence.append(f"runtime OS suite: missing {key} coverage")

        required_names = [item.capability for item in self.capabilities]
        missing_capabilities = [item for item in required_names if item not in covered]
        status = "pass"
        if missing_capabilities or missing_evidence:
            status = "fail" if required else "partial"
        return RuntimeOSGateEvaluation(
            required=required,
            status=status,
            covered_capabilities=[item for item in required_names if item in covered],
            missing_capabilities=missing_capabilities,
            missing_evidence=list(dict.fromkeys(missing_evidence)),
        )

    def _special_missing_message(self, scenario_name: str, key: str) -> str:
        if key == "candidate_isolated":
            return f"{scenario_name}: failed candidate polluted main workspace"
        if key == "promotion_failure_recorded":
            return f"{scenario_name}: candidate promotion failure was not recorded"
        if key == "failure_evidence":
            return f"{scenario_name}: missing failure evidence"
        if key == "merge_gate_blocked":
            return f"{scenario_name}: missing merge gate block"
        if key == "resume_recovered":
            return f"{scenario_name}: missing resume recovery"
        if key == "context_package_sliced":
            return f"{scenario_name}: context package was not sliced by read_scope"
        if key == "context_package_scope_partitioned":
            return f"{scenario_name}: context package did not separate read/write/evidence scopes"
        if key == "sandbox_backend_recorded":
            return f"{scenario_name}: missing sandbox backend and selection reason"
        if key == "planner_scope_narrowed":
            return f"{scenario_name}: planner did not narrow broad write_scope"
        if key == "runtime_request_created":
            return f"{scenario_name}: worker did not create an auditable runtime request"
        if key == "capability_feedback_recorded":
            return f"{scenario_name}: capability profile did not record runtime feedback signals"
        if key == "session_recovery_consumed_runtime_evidence":
            return f"{scenario_name}: session recovery did not consume Runtime OS evidence"
        if key == "review_consumed_runtime_evidence":
            return f"{scenario_name}: review did not consume Runtime OS evidence"
        if key == "session_recovery_consumed_failure_next_hint":
            return f"{scenario_name}: session recovery did not consume failure ToolObservation next_hint"
        if key == "review_consumed_failure_next_hint":
            return f"{scenario_name}: review did not consume failure ToolObservation next_hint"
        if key == "prompt_envelope_persisted":
            return f"{scenario_name}: missing persisted prompt envelope evidence"
        if key == "capability_manifest_layered":
            return f"{scenario_name}: capability manifest was not layered"
        if key == "project_guidance_section":
            return f"{scenario_name}: prompt envelope did not include project guidance"
        if key == "safety_budget_sections":
            return f"{scenario_name}: prompt envelope did not include safety and budget sections"
        if key == "delegation_brief_recorded":
            return f"{scenario_name}: delegation brief was not recorded in worker evidence"
        if key == "brief_quality_status_present":
            return f"{scenario_name}: brief quality gate status was not recorded"
        if key == "high_risk_delegation_blocked":
            return f"{scenario_name}: high-risk low-quality delegation was not blocked"
        if key == "scope_request_exception_recorded":
            return f"{scenario_name}: scope request exception was not recorded"
        if key == "delegation_evidence_consistent":
            return f"{scenario_name}: delegation worker/result/execution evidence is inconsistent"
        if key == "verification_commands_recorded":
            return f"{scenario_name}: no independent verification commands were recorded"
        if key == "review_evidence_present":
            return f"{scenario_name}: review agent did not produce an eval report"
        return f"{scenario_name}: missing {key}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
