from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.subagent_planner import (
    build_subagent_child_plan,
    persist_subagent_child_plan,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def _decision() -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": "agent-loop-decision-0001",
        "run_id": "run-1",
        "task_id": "task-parent",
        "created_at": "2026-05-29T10:00:00+08:00",
        "next_action": {
            "action": "subagent",
            "reason": "Delegate isolated implementation.",
            "target_task_id": "task-child",
            "capability_ref": {"type": "subagent", "name": "coder"},
            "expected_observation": {
                "summary": "Child implements and verifies the module.",
                "success_signal": "validation passes",
                "parallel_safety": "serial",
                "allowed_writes": ["src/notes_tool.py"],
            },
            "risk": "medium",
            "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
            "evidence_refs": ["task_plan.json"],
        },
    }


def test_subagent_child_plan_decomposes_parent_decision_into_child_task() -> None:
    plan = build_subagent_child_plan(
        decision=_decision(),
        execution_result={
            "execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0002",
            "worker_result_id": "worker-result-0002",
            "runtime_profile_id": "runtime-profile-worker-0002",
        },
        task={
            "task_id": "task-child",
            "title": "Create notes module",
            "allowed_tools": ["write_file", "run_command"],
            "validation_commands": ["pytest"],
        },
    )

    assert plan["subagent_child_plan_id"] == "subagent-child-plan-0001"
    assert plan["parent_task_id"] == "task-parent"
    assert plan["worker_invocation_id"] == "worker-0002"
    assert plan["decomposition_strategy"] == "single_child_task"
    assert plan["scheduling_strategy"] == "serial_single_worker"
    assert plan["child_tasks"][0]["write_scope"] == ["src/notes_tool.py"]
    assert plan["child_tasks"][0]["allowed_tools"] == ["write_file", "run_command"]
    SchemaValidator(Path("schemas")).validate("subagent_child_plan", plan)


def test_subagent_child_plan_persists_as_append_only_evidence(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    plan = persist_subagent_child_plan(
        run_dir=tmp_path,
        validator=validator,
        decision=_decision(),
        execution_result={
            "execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0002",
            "worker_result_id": "worker-result-0002",
            "runtime_profile_id": "runtime-profile-worker-0002",
        },
    )

    assert plan is not None
    lines = (tmp_path / "subagent_child_plans.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["subagent_child_plan_id"] == "subagent-child-plan-0001"


def test_subagent_child_plan_splits_disjoint_write_targets() -> None:
    decision = _decision()
    decision["next_action"]["expected_observation"] = {
        "summary": "Child workers can write independent files.",
        "parallel_safety": "disjoint_writes",
    }

    plan = build_subagent_child_plan(
        decision=decision,
        execution_result={
            "execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0002",
            "worker_result_id": "worker-result-0002",
            "runtime_profile_id": "runtime-profile-worker-0002",
        },
        task={
            "task_id": "task-child",
            "title": "Create independent docs",
            "acceptance": ["a exists", "b exists", "c exists"],
            "expected_artifacts": ["docs/a.md", "docs/b.md", "docs/c.md"],
            "write_scope": ["docs/a.md", "docs/b.md", "docs/c.md"],
            "allowed_tools": ["write_file", "run_command"],
            "parallel_safety": "disjoint_writes",
            "multi_agent_strategy": {
                "mode": "disjoint_write_workers",
                "max_child_workers": 3,
                "coordination_policy": {
                    "write_allowed": True,
                    "requires_disjoint_write_scope": True,
                    "requires_merge_gate": True,
                },
            },
        },
    )

    assert plan["decomposition_strategy"] == "disjoint_write_child_tasks"
    assert plan["scheduling_strategy"] == "parallel_disjoint_writes_after_merge_gate"
    assert plan["max_child_workers"] == 3
    assert [child["write_scope"] for child in plan["child_tasks"]] == [
        ["docs/a.md"],
        ["docs/b.md"],
        ["docs/c.md"],
    ]
    assert {child["worker_role"] for child in plan["child_tasks"]} == {"implementation_child"}
    assert all(child["write_allowed"] for child in plan["child_tasks"])
    SchemaValidator(Path("schemas")).validate("subagent_child_plan", plan)


def test_subagent_child_plan_splits_readonly_fanout_without_write_tools() -> None:
    decision = _decision()
    decision["next_action"]["expected_observation"] = {
        "summary": "Readonly checks can fan out.",
        "parallel_safety": "readonly",
    }

    plan = build_subagent_child_plan(
        decision=decision,
        execution_result={
            "execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0002",
            "worker_result_id": "worker-result-0002",
            "runtime_profile_id": "runtime-profile-worker-0002",
        },
        task={
            "task_id": "task-child",
            "task_kind": "research",
            "acceptance": ["inspect alpha", "inspect beta"],
            "read_scope": ["src/alpha.py", "src/beta.py"],
            "write_scope": [],
            "allowed_tools": ["read_file", "search_text", "write_file", "run_command"],
            "parallel_safety": "readonly",
            "multi_agent_strategy": {
                "mode": "readonly_fanout",
                "max_child_workers": 2,
                "coordination_policy": {
                    "write_allowed": False,
                    "requires_merge_gate": False,
                },
            },
        },
    )

    assert plan["decomposition_strategy"] == "readonly_fanout_child_tasks"
    assert plan["scheduling_strategy"] == "parallel_readonly_safe"
    assert len(plan["child_tasks"]) == 2
    assert all(child["write_scope"] == [] for child in plan["child_tasks"])
    assert all(child["write_allowed"] is False for child in plan["child_tasks"])
    assert all("write_file" not in child["allowed_tools"] for child in plan["child_tasks"])
    assert {child["worker_role"] for child in plan["child_tasks"]} == {"research_child"}
    SchemaValidator(Path("schemas")).validate("subagent_child_plan", plan)
