from __future__ import annotations

import json
import re
from pathlib import Path

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_command import GateCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.validation_run_command import ValidationRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_readme_points_to_existing_chinese_source_of_truth() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    doc_links = re.findall(r"`(docs/zh/[^`]+\.md)`", readme)

    assert doc_links, "README should link to Chinese documentation."
    assert any("研发总计划" in link for link in doc_links)
    assert any("当前状态" in link for link in doc_links)
    assert "docs/zh/研发总计划.md" in readme
    assert "docs/zh/当前状态与路线.md" in readme
    assert Path("docs/zh/研发总计划.md").exists()
    assert Path("docs/zh/当前状态与路线.md").exists()
    assert "slash-prefixed forms" in readme
    assert "compatibility aliases" in readme
    assert "`asteria accept` finalizes one reviewed run" in readme
    assert "`asteria acceptance` runs validation" in readme
    assert "not part of the ordinary user completion" in readme
    assert "path. Use plain command names" in readme
    assert "Maintainer-facing validation commands stay separate" in readme
    assert "`asteria gate`" in readme
    assert "`asteria validation-run --dry-run`" in readme
    assert "`asteria acceptance-gate`" in readme
    assert "研发总计划" in readme
    assert "`asteria goal" in readme


def test_runtime_command_docs_describe_accept_workflow_and_alias_policy() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")

    required_fragments = [
        "命令示例优先使用无斜杠形式",
        "Goal / Plan / Ask",
        "不是普通用户必须理解的线性流程",
        "init -> run -> status -> review -> accept",
        "runtime 阶段",
        "Acceptance review",
        "只要修改代码，就必须按需引入测试或等价验证",
        "### 3.8 `/accept`",
        "不等同于用于测试套件的 `acceptance`",
        "asteria accept --no-promote",
        "status=completed",
        "current_phase=ACCEPTED",
        "run_accepted",
        "DecisionPoint",
    ]

    for fragment in required_fragments:
        assert fragment in docs


def test_runtime_command_docs_describe_control_surface_contract() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")
    required_fragments = [
        "`asteria version --json`",
        "`asteria package-check --json`",
        "`asteria status --json`",
        "`asteria doctor --json`",
        "`asteria gate-status --json`",
        "`asteria gate --json`",
        "`asteria validation-run --dry-run --json`",
        "`asteria validation-run --json`",
        "`asteria weekly-report --json`",
        "`asteria roadmap-update --json`",
        "`control_surface`",
        "`stable_fields`",
        "`control_surface.stability` 当前为 `additive`",
        "DecisionPoint",
        "`status` uses `user_workflow`",
        "`doctor` use `maintainer_preflight`",
        "`gate-status` / `gate` use `maintainer_release_validation`",
        "`validation-run` uses `maintainer_validation_execution`",
        "`weekly-report` / `roadmap-update` use `maintainer_ops_reporting`",
        "docs/en/examples/version_control_surface.json",
        "docs/en/examples/package_check_control_surface.json",
        "docs/en/examples/status_control_surface.json",
        "docs/en/examples/doctor_control_surface.json",
        "docs/en/examples/gate_status_control_surface.json",
        "docs/en/examples/gate_control_surface.json",
        "docs/en/examples/validation_run_control_surface.json",
        "schemas/control_surface.schema.json",
        "`stability=additive`",
    ]

    for fragment in required_fragments:
        assert fragment in docs


def _load_control_surface_example(name: str) -> dict[str, object]:
    example_path = Path("docs/en/examples") / name
    return json.loads(example_path.read_text(encoding="utf-8"))


def _assert_control_surface_example_contract(
    payload: dict[str, object], *, command: str, audience: str
) -> None:
    contract = payload["control_surface"]
    assert isinstance(contract, dict)

    assert contract["schema_version"] == "0.1.0"
    assert contract["command"] == command
    assert contract["audience"] == audience
    assert contract["stability"] == "additive"
    assert set(contract["stable_fields"]) <= set(payload)
    assert payload["schema_version"] == contract["schema_version"]
    SchemaValidator(Path("schemas")).validate("control_surface", contract)


def _assert_example_stable_fields_match_runtime_payload(
    example_payload: dict[str, object], runtime_payload: dict[str, object]
) -> None:
    example_contract = example_payload["control_surface"]
    runtime_contract = runtime_payload["control_surface"]
    assert isinstance(example_contract, dict)
    assert isinstance(runtime_contract, dict)

    assert example_contract == runtime_contract
    for field in example_contract["stable_fields"]:
        assert field in example_payload
        assert field in runtime_payload
    assert example_payload["schema_version"] == runtime_payload["schema_version"]


def test_control_surface_examples_keep_runtime_stable_fields_in_sync(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    runtime_payloads = {
        "version_control_surface.json": VersionCommand().run().to_dict(),
        "package_check_control_surface.json": PackageCheckCommand(Path.cwd()).run().to_dict(),
        "status_control_surface.json": StatusCommand(tmp_path).run().to_dict(),
        "doctor_control_surface.json": DoctorCommand(tmp_path).run().to_dict(),
        "gate_status_control_surface.json": GateStatusCommand(tmp_path).run().to_dict(),
        "gate_control_surface.json": GateCommand(Path.cwd()).run().to_dict(),
        "validation_run_control_surface.json": ValidationRunCommand(Path.cwd(), dry_run=True).run().to_dict(),
    }

    for filename, runtime_payload in runtime_payloads.items():
        example_payload = _load_control_surface_example(filename)
        _assert_example_stable_fields_match_runtime_payload(
            example_payload, runtime_payload
        )


def test_control_surface_examples_match_documented_contracts() -> None:
    examples = [
        ("version_control_surface.json", "version", "maintainer_preflight"),
        ("package_check_control_surface.json", "package-check", "maintainer_preflight"),
        ("status_control_surface.json", "status", "user_workflow"),
        ("doctor_control_surface.json", "doctor", "maintainer_preflight"),
        (
            "gate_status_control_surface.json",
            "gate-status",
            "maintainer_release_validation",
        ),
        ("gate_control_surface.json", "gate", "maintainer_release_validation"),
        ("validation_run_control_surface.json", "validation-run", "maintainer_validation_execution"),
    ]

    for filename, command, audience in examples:
        payload = _load_control_surface_example(filename)
        _assert_control_surface_example_contract(
            payload, command=command, audience=audience
        )



def test_gate_control_surface_example_keeps_nested_stage_contracts_in_sync() -> None:
    payload = _load_control_surface_example("gate_control_surface.json")
    stages = payload["stages"]
    assert isinstance(stages, dict)

    expected_stage_examples = {
        "version": "version_control_surface.json",
        "package_check": "package_check_control_surface.json",
        "doctor": "doctor_control_surface.json",
        "gate_status": "gate_status_control_surface.json",
    }

    for stage_name, example_name in expected_stage_examples.items():
        stage_payload = stages[stage_name]
        assert isinstance(stage_payload, dict)
        expected_payload = _load_control_surface_example(example_name)
        assert stage_payload["control_surface"] == expected_payload["control_surface"]
        for field in expected_payload["control_surface"]["stable_fields"]:
            assert field in stage_payload


def test_validation_run_control_surface_summary_schema_requires_contract() -> None:
    schema = json.loads(Path("schemas/validation_run.schema.json").read_text(encoding="utf-8"))

    assert "control_surface" in schema["required"]
    control_surface = schema["properties"]["control_surface"]
    assert set(control_surface["required"]) == {
        "schema_version",
        "command",
        "audience",
        "stability",
        "stable_fields",
    }
    assert control_surface["properties"]["stability"]["enum"] == ["additive"]

def test_status_control_surface_example_keeps_user_workflow_next_action() -> None:
    payload = _load_control_surface_example("status_control_surface.json")

    assert payload["recommended_next_command"] == "resume"
    assert payload["next_actions"] == ["Run `asteria resume`."]


def test_runtime_command_docs_keep_user_workflow_sections_in_order() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")
    headings = [
        "### 3.6.1 `/resume`",
        "### 3.7 `/review`",
        "### 3.8 `/accept`",
        "### 3.9 `/debug`",
        "### 3.10 `/handoff`",
    ]

    positions = [docs.index(heading) for heading in headings]

    assert positions == sorted(positions)
    assert docs.count("### 3.8 ") == 1


def test_master_plan_exists_and_is_execution_entry() -> None:
    master_plan = Path("docs/zh/研发总计划.md")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    current_state = Path("docs/zh/当前状态与路线.md").read_text(encoding="utf-8")
    navigation = Path("docs/zh/文档导航.md").read_text(encoding="utf-8")

    assert master_plan.exists()
    body = master_plan.read_text(encoding="utf-8")
    assert "Vibe Slice" in body
    assert "代码 Triage 锁" in body
    assert "docs/zh/研发总计划.md" in agents
    assert "ACTIVE_SLICE" in agents
    assert "研发总计划" in current_state
    assert "研发总计划" in navigation
    assert Path("benchmarks/vibe_slices.json").exists()
    assert Path("benchmarks/reference_briefs/README.md").exists()
    assert Path("benchmarks/phase2_mvp_gate.json").exists()
    assert Path("benchmarks/phase3_rolling_gate.json").exists()
    assert Path("benchmarks/phase2_stability_gate.json").exists()
    assert Path("benchmarks/phase2_stability_window.json").exists()
    assert Path("benchmarks/phase4_steady_iteration_gate.json").exists()
    assert Path("benchmarks/phase5_swarm_gate.json").exists()
    assert Path("benchmarks/phase5b_swarm_rollout_gate.json").exists()
    assert Path("benchmarks/phase5c_swarm_integration_gate.json").exists()
    assert Path("benchmarks/phase5d_swarm_scenario_gate.json").exists()
    assert Path("benchmarks/phase5e_gray_decision_gate.json").exists()
    assert Path("benchmarks/phase5f_production_gray_gate.json").exists()
    assert Path("benchmarks/phase6_design_intel_gate.json").exists()
    assert Path("benchmarks/phase6b_design_intel_research_gate.json").exists()
    assert Path("benchmarks/phase6c_long_horizon_completion_gate.json").exists()
    assert Path("benchmarks/phase6d_goal_queue_gate.json").exists()
    assert Path("benchmarks/phase6e_supervised_goal_loop_gate.json").exists()
    assert Path("benchmarks/phase6f_local_background_run_gate.json").exists()
    assert Path("benchmarks/phase8a_slice_completion_judge_gate.json").exists()
    assert Path("benchmarks/phase8b_long_horizon_handoff_gate.json").exists()
    assert Path("benchmarks/phase8c_remote_background_adapter_gate.json").exists()
    assert Path("benchmarks/phase8_long_task_intelligence_gate.json").exists()
    assert Path("benchmarks/phase4_friction_gate.json").exists()
    assert Path("docs/zh/稳态迭代节奏.md").exists()
    current_state = Path("docs/zh/当前状态与路线.md").read_text(encoding="utf-8")
    assert Path("schemas/north_star.schema.json").exists()
    assert Path("docs/zh/plans/NORTH_STAR_RFC.md").exists()
    assert "综合下一步计划" in current_state


def test_active_slice_sources_agree() -> None:
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    slices = json.loads(Path("benchmarks/vibe_slices.json").read_text(encoding="utf-8"))
    snapshot = Path("docs/zh/当前状态与路线.md").read_text(encoding="utf-8")
    master = Path("docs/zh/研发总计划.md").read_text(encoding="utf-8")

    active_slice = slices["active_slice"]
    assert f"ACTIVE_SLICE：{active_slice}" in agents or f"ACTIVE_SLICE: {active_slice}" in agents
    assert active_slice in snapshot
    assert active_slice in master
    assert slices["active_phase"] in snapshot


def test_maintainer_pulse_reads_active_state_from_vibe_slices() -> None:
    pulse = Path("scripts/triple_track_pulse.py").read_text(encoding="utf-8")

    assert 'root / "benchmarks" / "vibe_slices.json"' in pulse
    assert '"active_slice": slices["active_slice"]' in pulse
    assert '"active_phase": slices["active_phase"]' in pulse
    assert '"active_slice": "S63"' not in pulse


def test_only_current_plan_and_brief_claim_active_status() -> None:
    allowed = {
        Path("docs/zh/plans/S74_POST_S73_BETA_CONVERGENCE_PLAN.md"),
        Path("benchmarks/reference_briefs/S74-post-s73-beta-convergence.md"),
    }
    candidates = [
        *Path("docs/zh/plans").glob("*.md"),
        *Path("benchmarks/reference_briefs").glob("*.md"),
    ]
    active = {
        path
        for path in candidates
        if re.search(r"状态[：:].{0,8}(?:\*\*)?(?:🔄\s*)?active\b", path.read_text(encoding="utf-8"), re.I)
    }

    assert active <= allowed


def test_agent_loop_limits_remain_eval_slos_not_universal_hard_stops() -> None:
    master = Path("docs/zh/研发总计划.md").read_text(encoding="utf-8")
    quality = Path("docs/zh/质量与评估.md").read_text(encoding="utf-8")
    active_plan = Path(
        "docs/zh/plans/S74_POST_S73_BETA_CONVERGENCE_PLAN.md"
    ).read_text(encoding="utf-8")
    adr = Path(
        "docs/zh/adr/0010-open-agent-loop-and-evaluation-boundaries.md"
    ).read_text(encoding="utf-8")

    assert "调用/repair 次数是 SLO，不是统一硬停止条件" in master
    assert "不得把统一低 model-call 或 repair 数量作为所有任务的 Runtime 完成门槛" in quality
    assert "不把 model/tool calls、repair/replan 或耗时 SLO 直接升级为所有任务的 Runtime 硬停止条件" in active_plan
    assert "开放 Agent Loop + 分层硬边界 + Eval/SLO 反馈" in adr


def test_complexity_liquidation_requires_reference_evidence_and_decision() -> None:
    master = Path("docs/zh/研发总计划.md").read_text(encoding="utf-8")
    governance = Path("docs/zh/工程治理体系.md").read_text(encoding="utf-8")
    active_plan = Path(
        "docs/zh/plans/S74_POST_S73_BETA_CONVERGENCE_PLAN.md"
    ).read_text(encoding="utf-8")
    adr = Path(
        "docs/zh/adr/0011-reference-first-complexity-liquidation.md"
    ).read_text(encoding="utf-8")
    register = Path(
        "docs/zh/plans/S74_COMPLEXITY_LIQUIDATION_REGISTER.md"
    ).read_text(encoding="utf-8")

    assert "自研愿景不能保护劣质实现" in master
    assert "Reference-First Complexity Liquidation" in governance
    assert "确认当前实现劣于成熟产品的稳定原语后" in active_plan
    assert "产品必要性" in adr
    assert "成熟参考与机制合理性" in adr
    assert "可测产品收益" in adr
    assert "实现质量与可替换性" in adr
    assert "REPLACE_IMPLEMENTATION" in register
    assert "DELETE" in register


def test_studio_main_path_uses_session_transcript_not_runtime_projection() -> None:
    adr = Path(
        "docs/zh/adr/0012-session-transcript-as-studio-main-path.md"
    ).read_text(encoding="utf-8")
    studio_rules = Path("docs/zh/Studio 会话与上下文设计准则.md").read_text(
        encoding="utf-8"
    )
    runtime_narrative = Path(
        "studio/src/features/thread/runtimeNarrative.ts"
    ).read_text(encoding="utf-8")

    assert "Studio 主会话只消费 `user_progress`" in adr
    assert "主会话 timeline 只消费 `user_progress`" in studio_rules
    assert "synthesizedRuntimeProgressEvents" not in runtime_narrative
    assert "runtime-progress-${runId" not in runtime_narrative
    assert "if (!event.transcript_kind) return null" in runtime_narrative
    assert "events.push(...userProgress)" in runtime_narrative
    assert not Path("studio/src/components/WorkflowPhaseStrip.tsx").exists()


def test_runtime_risk_is_enforced_at_action_boundaries() -> None:
    gate_status = Path(
        "src/asteria_runtime/commands/gate_status_command.py"
    ).read_text(encoding="utf-8")
    validation_run = Path(
        "src/asteria_runtime/commands/validation_run_command.py"
    ).read_text(encoding="utf-8")
    adr = Path(
        "docs/zh/adr/0013-enforce-risk-at-action-boundaries.md"
    ).read_text(encoding="utf-8")

    assert not Path("src/asteria_runtime/core/runtime_readiness_gate.py").exists()
    assert "runtime_readiness_gate" not in gate_status
    assert "_allow_targeted_probe_over_runtime_readiness" not in validation_run
    assert "runtime_readiness_gate" not in validation_run
    assert "动作边界" in adr


def test_run_recovery_has_one_default_controller() -> None:
    run_command = Path("src/asteria_runtime/commands/run_command.py").read_text(encoding="utf-8")
    review_command = Path("src/asteria_runtime/commands/review_command.py").read_text(
        encoding="utf-8"
    )
    adr = Path(
        "docs/zh/adr/0014-single-session-recovery-and-explicit-review.md"
    ).read_text(encoding="utf-8")

    assert "from asteria_runtime.commands.debug_command import DebugCommand" not in run_command
    assert "from asteria_runtime.commands.review_command import ReviewCommand" not in run_command
    assert "DebugCommand(" not in run_command
    assert "ReviewCommand(" not in run_command
    assert "_goal_loop_decision" not in run_command
    assert "FollowUpTaskPlanner" not in review_command
    assert "DecideCommand" not in review_command
    assert "persist_runtime_agent_loop_decision" not in review_command
    assert "persist_agent_loop_execution_result" not in review_command
    assert "单 Session 恢复" in adr


def test_system_audit_forbids_fake_success_and_dead_follow_up_orchestration() -> None:
    verdict = Path("docs/zh/plans/S74_SYSTEM_AUDIT_VERDICT.md").read_text(encoding="utf-8")
    smoke = Path("src/asteria_runtime/real_model_smoke.py").read_text(encoding="utf-8")
    gate = Path("src/asteria_runtime/real_model_gate.py").read_text(encoding="utf-8")
    acceptance = Path("src/asteria_runtime/real_model_acceptance.py").read_text(encoding="utf-8")
    planner = Path("src/asteria_runtime/agents/planner.py").read_text(encoding="utf-8")

    assert "完整裁决矩阵" in verdict
    assert "FollowUpTaskPlanner" not in planner
    assert not Path("src/asteria_runtime/core/decision_policy.py").exists()
    assert "_write_review_timeout_artifacts" not in smoke
    assert "_write_artifact_verified_fallback_artifacts" not in smoke
    assert "salvage_timed_out_smoke_summary" not in gate
    assert "salvage_timed_out_smoke_summary" not in acceptance


def test_product_architecture_is_session_loop_not_global_state_machine() -> None:
    architecture = Path("docs/zh/架构设计.md").read_text(encoding="utf-8")
    baseline = Path(
        "docs/zh/plans/S74_REFERENCE_PRODUCT_BASELINE.md"
    ).read_text(encoding="utf-8")
    adr = Path(
        "docs/zh/adr/0015-session-loop-is-product-architecture.md"
    ).read_text(encoding="utf-8")

    assert "连续 Session Agent Loop" in architecture
    assert "model -> action -> observation -> model" in architecture
    assert "状态字段只服务于持久化、恢复和查证" in adr
    assert "Claude Code" in baseline
    assert "Codex" in baseline
    assert "OpenCode" in baseline

    forbidden_architecture_claims = [
        "Runtime first, agents second",
        "TaskGraph 优先于线性对话",
        "## 5. 状态机",
        "编排器状态转换",
        "产品生产控制平面",
        "PlannerAgent",
        "ReviewAgent 汇总差异",
    ]
    for claim in forbidden_architecture_claims:
        assert claim not in architecture
