from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.design_intel_contract import (
    PILOT_RESEARCH_TYPES,
    apply_design_intel_contract,
    apply_research_type_to_goal_spec,
    apply_research_type_to_task_plan,
    infer_research_type,
    normalize_research_type,
    pilot_research_types,
)


def test_pilot_research_types_match_phase6_gate() -> None:
    gate = json.loads(Path("benchmarks/phase6_design_intel_gate.json").read_text(encoding="utf-8"))
    assert set(pilot_research_types()) == set(gate["pilot_scope"]["research_types"])
    assert PILOT_RESEARCH_TYPES == frozenset({"documentation", "creative", "research"})


def test_normalize_research_type_documentation() -> None:
    assert normalize_research_type("documentation") == "documentation"


def test_normalize_research_type_creative() -> None:
    assert normalize_research_type(" Creative ") == "creative"


def test_normalize_research_type_research() -> None:
    assert normalize_research_type("research") == "research"


def test_normalize_research_type_invalid() -> None:
    assert normalize_research_type("product_research") is None
    assert normalize_research_type("") is None
    assert normalize_research_type(None) is None


def test_infer_from_explicit_field() -> None:
    goal_spec = {"goal_type": "software_tool", "research_type": "creative"}
    assert infer_research_type(goal_spec) == "creative"


def test_infer_from_goal_type_report() -> None:
    goal_spec = {
        "goal_type": "report",
        "original_goal": "Summarize findings",
        "normalized_goal": "Summarize findings",
    }
    assert infer_research_type(goal_spec) == "documentation"


def test_infer_from_goal_text_documentation() -> None:
    goal_spec = {
        "goal_type": "unknown",
        "original_goal": "Write API documentation for the CLI",
        "normalized_goal": "Write API documentation for the CLI",
        "target_outputs": ["docs/README.md"],
    }
    assert infer_research_type(goal_spec) == "documentation"


def test_infer_from_goal_text_creative() -> None:
    goal_spec = {
        "goal_type": "unknown",
        "original_goal": "Brainstorm creative UI mockups for onboarding",
        "normalized_goal": "Brainstorm creative UI mockups for onboarding",
    }
    assert infer_research_type(goal_spec) == "creative"


def test_software_tool_goal_has_no_research_type() -> None:
    goal_spec = {
        "goal_type": "software_tool",
        "original_goal": "Build a password checker CLI",
        "normalized_goal": "Build a password checker CLI",
    }
    assert infer_research_type(goal_spec) is None
    assert "research_type" not in apply_research_type_to_goal_spec(goal_spec)


def test_apply_research_type_to_task_plan_propagates() -> None:
    goal_spec = {"research_type": "documentation"}
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [{"task_id": "task-0001", "title": "Write docs"}],
    }
    updated = apply_research_type_to_task_plan(goal_spec, task_plan)
    assert updated["tasks"][0]["research_type"] == "documentation"


def test_apply_design_intel_contract_end_to_end() -> None:
    goal_spec = {
        "goal_type": "report",
        "original_goal": "Draft release notes documentation",
        "normalized_goal": "Draft release notes documentation",
    }
    task_plan = {"schema_version": "0.1.0", "tasks": [{"task_id": "task-0001"}]}
    goal, plan = apply_design_intel_contract(goal_spec, task_plan)
    assert goal["research_type"] == "documentation"
    assert plan is not None
    assert plan["tasks"][0]["research_type"] == "documentation"
