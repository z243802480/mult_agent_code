from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PILOT_RESEARCH_TYPES: frozenset[str] = frozenset({"documentation", "creative", "research"})
_PHASE6_GATE_PATH = Path("benchmarks/phase6_design_intel_gate.json")
_PHASE6B_GATE_PATH = Path("benchmarks/phase6b_design_intel_research_gate.json")

# Default mapping: all `/research --type` values bridge to pilot `research` unless overridden.
_DEFAULT_CLI_TO_PLAN: dict[str, str] = {
    "general": "research",
    "product_research": "research",
    "architecture_research": "research",
    "implementation_research": "research",
    "competitive_research": "research",
    "paper_research": "research",
    "open_source_research": "research",
    "risk_research": "research",
    "design_pattern_research": "research",
}


def research_cli_types() -> tuple[str, ...]:
    """Load `/research --type` values from the Phase 6b gate manifest."""
    if not _PHASE6B_GATE_PATH.exists():
        return tuple(_DEFAULT_CLI_TO_PLAN.keys())
    gate = json.loads(_PHASE6B_GATE_PATH.read_text(encoding="utf-8"))
    bridge = gate.get("bridge_scope") or {}
    values = bridge.get("research_cli_types")
    if isinstance(values, list) and values:
        return tuple(str(item) for item in values)
    return tuple(_DEFAULT_CLI_TO_PLAN.keys())


def map_research_cli_type_to_plan_type(cli_type: object) -> str | None:
    if not isinstance(cli_type, str):
        return None
    normalized = cli_type.strip().lower()
    if not normalized:
        return None
    if normalized in PILOT_RESEARCH_TYPES:
        return normalized
    if normalized in research_cli_types():
        return _DEFAULT_CLI_TO_PLAN.get(normalized, "research")
    return None


def pilot_research_types() -> tuple[str, ...]:
    """Load pilot research types from the Phase 6 gate manifest."""
    if not _PHASE6_GATE_PATH.exists():
        return tuple(sorted(PILOT_RESEARCH_TYPES))
    gate = json.loads(_PHASE6_GATE_PATH.read_text(encoding="utf-8"))
    pilot = gate.get("pilot_scope") or {}
    values = pilot.get("research_types")
    if isinstance(values, list) and values:
        return tuple(str(item) for item in values)
    return tuple(sorted(PILOT_RESEARCH_TYPES))


def normalize_research_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in PILOT_RESEARCH_TYPES else None


def _goal_text(goal_spec: dict[str, Any]) -> str:
    parts: list[str] = [
        str(goal_spec.get("original_goal") or ""),
        str(goal_spec.get("normalized_goal") or ""),
    ]
    for key in ("target_outputs", "definition_of_done", "verification_strategy", "constraints"):
        items = goal_spec.get(key)
        if isinstance(items, list):
            parts.extend(str(item) for item in items if item)
    for requirement in goal_spec.get("expanded_requirements") or []:
        if isinstance(requirement, dict):
            parts.append(str(requirement.get("description") or ""))
    return " ".join(parts).lower()


def infer_research_type(goal_spec: dict[str, Any]) -> str | None:
    explicit = normalize_research_type(goal_spec.get("research_type"))
    if explicit:
        return explicit

    cli_mapped = map_research_cli_type_to_plan_type(goal_spec.get("research_cli_type"))
    if cli_mapped:
        return cli_mapped

    goal_type = str(goal_spec.get("goal_type") or "").strip().lower()
    if goal_type in {"report", "knowledge_base"}:
        return "documentation"
    if goal_type == "research":
        return "research"

    text = _goal_text(goal_spec)
    creative_markers = (
        "creative",
        "brainstorm",
        "design mock",
        "ui mock",
        "mockup",
        "storyboard",
        "创意",
        "设计稿",
    )
    if any(marker in text for marker in creative_markers):
        return "creative"

    documentation_markers = (
        "documentation",
        "readme",
        "user guide",
        "api doc",
        "doc ",
        "docs/",
        "文档",
        "说明文档",
        "markdown report",
    )
    if any(marker in text for marker in documentation_markers):
        return "documentation"

    research_markers = (
        "research",
        "investigate",
        "competitive",
        "architecture review",
        "调研",
        "竞品",
        "可行性",
    )
    if any(marker in text for marker in research_markers):
        return "research"

    return None


def apply_research_type_to_goal_spec(goal_spec: dict[str, Any]) -> dict[str, Any]:
    result = dict(goal_spec)
    inferred = infer_research_type(result)
    if inferred:
        result["research_type"] = inferred
    else:
        result.pop("research_type", None)
    return result


def apply_research_type_to_task_plan(
    goal_spec: dict[str, Any],
    task_plan: dict[str, Any],
) -> dict[str, Any]:
    research_type = goal_spec.get("research_type")
    if not isinstance(research_type, str) or not research_type:
        return task_plan
    result = dict(task_plan)
    tasks: list[Any] = []
    promote_research_task = bool(goal_spec.get("research_cli_type"))
    for index, task in enumerate(result.get("tasks") or []):
        if not isinstance(task, dict):
            tasks.append(task)
            continue
        updated = dict(task)
        updated["research_type"] = research_type
        if promote_research_task and index == 0:
            updated["task_kind"] = "research"
            updated.pop("execution_profile", None)
        tasks.append(updated)
    result["tasks"] = tasks
    return result


def apply_design_intel_contract(
    goal_spec: dict[str, Any],
    task_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    goal = apply_research_type_to_goal_spec(goal_spec)
    plan = (
        apply_research_type_to_task_plan(goal, task_plan)
        if task_plan is not None
        else None
    )
    return goal, plan
