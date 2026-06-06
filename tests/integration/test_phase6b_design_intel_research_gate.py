from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.research_command import ResearchCommand
from asteria_runtime.core.design_intel_contract import (
    map_research_cli_type_to_plan_type,
    research_cli_types,
)
from asteria_runtime.core.design_intel_research_bridge import (
    run_design_intel_research_band,
)
from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_phase6_design_intel_gate import DesignIntelFakeClient
from tests.integration.test_research_command import FakeResearchClient

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase6b_design_intel_research_gate.json").read_text(encoding="utf-8")
)


def _load_user_progress(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_phase6b_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "2"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    bridge = GATE["bridge_scope"]
    assert bridge["session_agent_default_unchanged"] is True
    assert set(bridge["research_cli_types"]) == set(research_cli_types())
    assert "product_research" in bridge["research_cli_types"]
    assert "documentation" in bridge["plan_pilot_types"]


@pytest.mark.parametrize(
    "cli_type",
    [
        "general",
        "product_research",
        "architecture_research",
        "competitive_research",
    ],
)
def test_research_cli_type_maps_to_plan_research(cli_type: str) -> None:
    assert map_research_cli_type_to_plan_type(cli_type) == "research"


def test_research_then_plan_links_report_and_user_progress(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "password.md").write_text(
        "Password tools should check length, character diversity, and common passwords.\n",
        encoding="utf-8",
    )

    research = ResearchCommand(
        tmp_path,
        "password tool requirements",
        research_type="product_research",
        model_client=FakeResearchClient(),
    ).run()
    goal = "Build a password tool informed by product research"
    plan = PlanCommand(
        tmp_path,
        goal,
        run_id=research.run_id,
        model_client=DesignIntelFakeClient(
            goal_type="research",
            normalized_goal=goal,
            research_type="research",
        ),
    ).run()

    goal_spec = json.loads(plan.goal_spec_path.read_text(encoding="utf-8"))
    assert goal_spec.get("research_cli_type") == "product_research"
    assert goal_spec.get("research_type") == "research"
    assert goal_spec.get("research_report_ref", "").endswith("research_report.json")
    assert any(
        item.get("source") == "research"
        for item in goal_spec.get("expanded_requirements") or []
        if isinstance(item, dict)
    )

    task_plan = json.loads(plan.task_plan_path.read_text(encoding="utf-8"))
    assert task_plan["tasks"][0].get("task_kind") == "research"
    assert task_plan["tasks"][0].get("research_type") == "research"

    run_dir = tmp_path / ".asteria" / "runs" / research.run_id
    loop_dispatch = json.loads((run_dir / "agent_loop_dispatch.json").read_text(encoding="utf-8"))
    assert loop_dispatch.get("profile_counts", {}).get("research", 0) >= 1

    progress = _load_user_progress(run_dir)
    assert any(event.get("title") == "Research report linked to plan" for event in progress)
    linked = next(event for event in progress if event.get("title") == "Research report linked to plan")
    assert linked["data"].get("research_cli_type") == "product_research"
    assert linked["data"].get("plan_research_type") == "research"


def test_design_intel_research_band_closes_phase6b_contract(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    band = run_design_intel_research_band(tmp_path, validator)
    assert band.ok is True
    assert band.research_cli_type == "product_research"
    assert band.plan_research_type == "research"
    assert band.research_profile_dispatched is True


def test_runtime_matrix_profile_research_passes_after_band(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    assert run_design_intel_research_band(tmp_path, validator).ok is True
    metrics = runtime_progress_metrics(tmp_path, validator)
    matrix = runtime_validation_matrix(tmp_path, metrics)
    research_case = next(item for item in matrix["cases"] if item["id"] == "profile_research")
    assert research_case["ok"] is True
