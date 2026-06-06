from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.agent_loop_executor import (
    build_agent_loop_execution_result,
    persist_agent_loop_execution_result,
    persist_subagent_child_plan_for_execution,
)
from asteria_runtime.core.agent_loop_decision import persist_agent_loop_decision
from asteria_runtime.storage.schema_validator import SchemaValidator


def _disjoint_task() -> dict:
    return {
        "task_id": "task-disjoint-1",
        "title": "Parallel disjoint implementation",
        "parallel_safety": "disjoint_writes",
        "write_scope": ["src/a.py", "src/b.py"],
        "multi_agent_strategy": {
            "mode": "disjoint_write_workers",
            "max_child_workers": 2,
            "coordination_policy": {"requires_disjoint_write_scope": True},
        },
    }


def _subagent_decision() -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": "agent-loop-decision-disjoint-0001",
        "run_id": "run-disjoint-1",
        "task_id": "task-disjoint-1",
        "created_at": "2026-06-06T12:00:00+08:00",
        "next_action": {
            "action": "subagent",
            "reason": "Delegate disjoint child workers.",
            "target_task_id": "task-disjoint-1",
            "capability_ref": {"type": "subagent", "name": "disjoint_write_workers"},
            "expected_observation": {
                "summary": "Two disjoint workers complete scoped writes.",
                "write_scope": ["src/a.py", "src/b.py"],
                "parallel_safety": "disjoint_writes",
            },
            "risk": "medium",
            "budget_hint": {"model_calls": 2, "tool_budget_units": 0},
            "evidence_refs": [],
        },
    }


def test_agent_loop_subagent_persists_swarm_execution_plan(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    decision = _subagent_decision()
    persist_agent_loop_decision(run_dir=tmp_path, validator=validator, decision=decision)
    execution = persist_agent_loop_execution_result(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
    )
    assert isinstance(execution, dict)
    child_plan = persist_subagent_child_plan_for_execution(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
        execution_result=execution,
        task=_disjoint_task(),
    )
    assert isinstance(child_plan, dict)
    assert len(child_plan.get("child_tasks") or []) == 2

    plans = [
        json.loads(line)
        for line in (tmp_path / "swarm_execution_plans.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(plans) == 1
    latest = plans[0]
    assert latest["scheduling_mode"] == "fake_serial"
    assert latest["fake_path"] is True
    assert latest["parallel_writes"] is False
    assert latest["subagent_child_plan_id"] == child_plan["subagent_child_plan_id"]

    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("type") == "swarm_execution_planned" for event in events)
    assert any(event.get("type") == "swarm_execution_plan_persisted" for event in events)


def test_swarm_execution_plan_with_maintainer_probe_policy(tmp_path: Path) -> None:
    from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy

    validator = SchemaValidator(Path("schemas"))
    decision = _subagent_decision()
    execution = build_agent_loop_execution_result(decision)
    execution["worker_invocation_id"] = "worker-disjoint-0001"
    execution["worker_result_id"] = "worker-result-disjoint-0001"
    execution["runtime_profile_id"] = "runtime-profile-disjoint-0001"
    child_plan = persist_subagent_child_plan_for_execution(
        run_dir=tmp_path,
        validator=validator,
        decision=decision,
        execution_result=execution,
        task=_disjoint_task(),
        policy=with_maintainer_probe_policy({}),
    )
    assert isinstance(child_plan, dict)
    plans = [
        json.loads(line)
        for line in (tmp_path / "swarm_execution_plans.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert plans[-1]["scheduling_mode"] == "parallel"
    assert plans[-1]["fake_path"] is False
    assert plans[-1]["parallel_writes"] is True
