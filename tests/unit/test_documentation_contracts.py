from __future__ import annotations

import json
import re
from pathlib import Path

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_readme_points_to_existing_chinese_source_of_truth() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    match = re.search(r"`(docs/zh/[^`]+\.md)`", readme)

    assert match, "README should link to the Chinese current-state source of truth."
    assert "当前状态" in match.group(1)
    assert Path(match.group(1)).exists()
    assert "slash-prefixed forms" in readme
    assert "compatibility aliases" in readme
    assert "`asteria accept` finalizes one reviewed run" in readme
    assert "`asteria acceptance` runs validation" in readme
    assert "not part of the ordinary user completion" in readme
    assert "path. Use plain command names" in readme
    assert "Maintainer-facing validation commands stay separate" in readme
    assert "`asteria gate`" in readme
    assert "`asteria gray`" in readme
    assert "`asteria acceptance-gate`" in readme


def test_runtime_command_docs_describe_accept_workflow_and_alias_policy() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")

    required_fragments = [
        "命令示例优先使用无斜杠形式",
        "init -> run -> status -> resume -> review -> accept",
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
        "`control_surface`",
        "`stable_fields`",
        "`control_surface.stability` 当前为 `additive`",
        "DecisionPoint",
        "`status` 使用 `user_workflow`",
        "`doctor` 使用 `maintainer_preflight`",
        "`gate-status` 使用 `maintainer_release_readiness`",
        "docs/en/examples/status_control_surface.json",
        "docs/en/examples/doctor_control_surface.json",
        "docs/en/examples/gate_status_control_surface.json",
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
        "status_control_surface.json": StatusCommand(tmp_path).run().to_dict(),
        "doctor_control_surface.json": DoctorCommand(tmp_path).run().to_dict(),
        "gate_status_control_surface.json": GateStatusCommand(tmp_path).run().to_dict(),
    }

    for filename, runtime_payload in runtime_payloads.items():
        example_payload = _load_control_surface_example(filename)
        _assert_example_stable_fields_match_runtime_payload(
            example_payload, runtime_payload
        )


def test_control_surface_examples_match_documented_contracts() -> None:
    examples = [
        ("status_control_surface.json", "status", "user_workflow"),
        ("doctor_control_surface.json", "doctor", "maintainer_preflight"),
        (
            "gate_status_control_surface.json",
            "gate-status",
            "maintainer_release_readiness",
        ),
    ]

    for filename, command, audience in examples:
        payload = _load_control_surface_example(filename)
        _assert_control_surface_example_contract(
            payload, command=command, audience=audience
        )


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
