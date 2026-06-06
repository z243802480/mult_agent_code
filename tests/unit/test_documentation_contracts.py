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
