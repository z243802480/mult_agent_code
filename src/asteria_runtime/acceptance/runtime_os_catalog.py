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
        # spine 直写模型:失败态被正确性 gate 拦为 blocked(错误产物留盘·不被接受),证据为
        # task_execution_evidence(contract 不 ok)——取代 FSM 的候选隔离/晋升失败语义。
        special_evidence=("failure_blocked", "failure_evidence"),
    ),
    RuntimeOSCapability(
        scenario="runtime_merge_gate_block",
        capability="runtime_merge_gate_block",
        special_evidence=("merge_gate_blocked",),
    ),
    RuntimeOSCapability(
        scenario="runtime_context_package_slice",
        capability="context_package_slice",
        # spine 把 scoped context 渲进提示词(非 payload 字段),集成证据=per-task coding_context
        # 挂载(context_mounts.jsonl·含 goal/task brief)且任务只用其 read_scope 收口;细粒度"入/出
        # scope 文件切片"由 context_package_builder 单测覆盖。
        special_evidence=("context_mount_built", "context_scope_applied"),
    ),
    RuntimeOSCapability(
        scenario="runtime_sandbox_backend_selection",
        capability="sandbox_backend_selection",
        special_evidence=("sandbox_backend_recorded",),
    ),
    RuntimeOSCapability(
        scenario="runtime_independent_verification",
        capability="independent_verification",
        required_evidence=(),
        suite_evidence=(),
        special_evidence=("verification_commands_recorded", "review_evidence_present"),
    ),
)
# RA7b slice 4: five runtime-OS capabilities were retired with the FSM round loop — they validated
# mechanisms the model-driven spine deliberately does not have: human-gated per-tool scope expansion
# (runtime_request_resume, planner_scope_quality — spine denies-and-blocks, scope changes live at
# goal-level replan per AGENTS.md §11), the FSM delegation-brief quality gate (delegation_contract —
# the spine bounds delegation via spawn_subagent depth-guard instead), runtime_request-derived
# capability feedback (capability_feedback), and FSM-worker session-recovery evidence
# (runtime_evidence_consumption). worker_failure + context_package_slice were migrated to spine-native
# evidence (direct-write blocked + task_execution_evidence; context_mounts.jsonl scope). See
# docs/zh/研发总计划.md §16.


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

