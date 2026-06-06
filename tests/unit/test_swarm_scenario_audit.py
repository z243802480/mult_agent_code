from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.swarm_scenario_audit import SwarmScenarioAuditor
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_scenario_audit_detects_subagent_swarm_path(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / "run-subagent"
    run_dir.mkdir()
    child = {
        "schema_version": "0.1.0",
        "subagent_child_plan_id": "subagent-child-plan-0001",
        "run_id": "run-1",
        "parent_task_id": "task-1",
        "target_task_id": "task-1",
        "parent_decision_id": "d1",
        "parent_execution_id": "e1",
        "worker_invocation_id": "w1",
        "worker_result_id": "wr1",
        "runtime_profile_id": "rp1",
        "planner_id": "p",
        "decomposition_strategy": "disjoint_write_child_tasks",
        "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
        "max_child_workers": 2,
        "coordination_policy": {},
        "status": "planned",
        "parallel_safety": "disjoint_writes",
        "child_tasks": [],
        "evidence_refs": [],
        "created_at": "2026-06-06T12:00:00+08:00",
    }
    swarm = {
        "schema_version": "0.1.0",
        "swarm_execution_plan_id": "swarm-exec-plan-0001",
        "subagent_child_plan_id": "subagent-child-plan-0001",
        "run_id": "run-1",
        "parent_task_id": "task-1",
        "scheduling_mode": "fake_serial",
        "fake_path": True,
        "parallel_writes": False,
        "spawn_plan": {},
        "child_task_ids": ["c1", "c2"],
        "created_at": "2026-06-06T12:00:00+08:00",
    }
    (run_dir / "subagent_child_plans.jsonl").write_text(
        json.dumps(child, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "swarm_execution_plans.jsonl").write_text(
        json.dumps(swarm, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result = SwarmScenarioAuditor(validator).evaluate_run_dir(run_dir)
    assert result.ok is True
    assert "subagent_swarm_planning" in result.detected_paths


def test_scenario_audit_rejects_empty_run_dir(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / "run-empty"
    run_dir.mkdir()
    result = SwarmScenarioAuditor(validator).evaluate_run_dir(run_dir)
    assert result.ok is False
    assert result.detected_paths == []
