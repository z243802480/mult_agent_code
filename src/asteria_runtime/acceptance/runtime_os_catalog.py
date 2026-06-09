from __future__ import annotations

from dataclasses import dataclass


COMMON_RUNTIME_OS_EVIDENCE = (
    "workers_jsonl",
    "worker_results_jsonl",
    "runtime_profiles_jsonl",
    "context_mounts_jsonl",
    "task_execution_evidence_jsonl",
)
AGGREGATE_RUNTIME_OS_EVIDENCE = ("validation_results_jsonl",)


@dataclass(frozen=True)
class RuntimeOSCapability:
    scenario: str
    capability: str
    tier: str = "core"
    kind: str = "runtime_os"
    required_evidence: tuple[str, ...] = COMMON_RUNTIME_OS_EVIDENCE
    suite_evidence: tuple[str, ...] = AGGREGATE_RUNTIME_OS_EVIDENCE
    special_evidence: tuple[str, ...] = ()


RUNTIME_OS_CAPABILITIES: tuple[RuntimeOSCapability, ...] = (
    RuntimeOSCapability(
        scenario="runtime_prompt_envelope",
        capability="prompt_envelope",
        required_evidence=(),
        suite_evidence=(),
        special_evidence=(
            "prompt_envelope_persisted",
            "capability_manifest_layered",
            "project_guidance_section",
            "safety_budget_sections",
        ),
    ),
    RuntimeOSCapability(
        scenario="runtime_parallel_readonly",
        capability="runtime_parallel_readonly",
    ),
    RuntimeOSCapability(
        scenario="runtime_disjoint_writes",
        capability="runtime_disjoint_writes",
    ),
    RuntimeOSCapability(
        scenario="runtime_worker_failure",
        capability="runtime_worker_failure",
        special_evidence=("failure_evidence", "candidate_isolated", "promotion_failure_recorded"),
    ),
    RuntimeOSCapability(
        scenario="runtime_merge_gate_block",
        capability="runtime_merge_gate_block",
        special_evidence=("merge_gate_blocked",),
    ),
    RuntimeOSCapability(
        scenario="runtime_request_resume",
        capability="runtime_request_resume",
        special_evidence=("resume_recovered",),
    ),
    RuntimeOSCapability(
        scenario="runtime_context_package_slice",
        capability="context_package_slice",
        special_evidence=("context_package_sliced", "context_package_scope_partitioned"),
    ),
    RuntimeOSCapability(
        scenario="runtime_sandbox_backend_selection",
        capability="sandbox_backend_selection",
        special_evidence=("sandbox_backend_recorded",),
    ),
    RuntimeOSCapability(
        scenario="runtime_planner_scope_quality",
        capability="planner_scope_quality",
        special_evidence=("planner_scope_narrowed", "runtime_request_created"),
    ),
    RuntimeOSCapability(
        scenario="runtime_capability_feedback",
        capability="capability_feedback",
        special_evidence=("capability_feedback_recorded",),
    ),
    RuntimeOSCapability(
        scenario="runtime_evidence_consumption",
        capability="runtime_evidence_consumption",
        special_evidence=(
            "session_recovery_consumed_runtime_evidence",
            "review_consumed_runtime_evidence",
            "session_recovery_consumed_failure_next_hint",
            "review_consumed_failure_next_hint",
        ),
    ),
    RuntimeOSCapability(
        scenario="runtime_delegation_contract",
        capability="delegation_contract",
        required_evidence=(),
        suite_evidence=(),
        special_evidence=(
            "delegation_brief_recorded",
            "brief_quality_status_present",
            "high_risk_delegation_blocked",
            "scope_request_exception_recorded",
            "delegation_evidence_consistent",
        ),
    ),
    RuntimeOSCapability(
        scenario="runtime_independent_verification",
        capability="independent_verification",
        required_evidence=(),
        suite_evidence=(),
        special_evidence=("verification_commands_recorded", "review_evidence_present"),
    ),
)


def runtime_os_scenario_names() -> list[str]:
    return [item.scenario for item in RUNTIME_OS_CAPABILITIES]


def runtime_os_capability_names() -> list[str]:
    return [item.capability for item in RUNTIME_OS_CAPABILITIES]


def runtime_os_capability_map() -> dict[str, RuntimeOSCapability]:
    return {item.capability: item for item in RUNTIME_OS_CAPABILITIES}


def runtime_os_metadata() -> list[dict[str, str]]:
    return [
        {
            "scenario": item.scenario,
            "capability": item.capability,
            "tier": item.tier,
            "kind": item.kind,
        }
        for item in RUNTIME_OS_CAPABILITIES
    ]

