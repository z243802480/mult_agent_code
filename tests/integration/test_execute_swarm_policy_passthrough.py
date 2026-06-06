from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.subagent_planner import build_subagent_child_plan
from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy
from asteria_runtime.core.swarm_orchestrator import plan_swarm_execution
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from tests.integration.test_execute_command import FakePlanClient, FakeSubagentExecuteClient


def test_build_subagent_child_plan_uses_policy_for_spawn_hints() -> None:
    decision = {
        "schema_version": "0.1.0",
        "decision_id": "decision-disjoint",
        "run_id": "run-disjoint",
        "task_id": "task-parent",
        "created_at": "2026-06-06T12:00:00+08:00",
        "next_action": {
            "action": "subagent",
            "reason": "Delegate disjoint workers.",
            "target_task_id": "task-parent",
            "capability_ref": {"type": "subagent", "name": "disjoint_write_workers"},
            "expected_observation": {
                "parallel_safety": "disjoint_writes",
                "allowed_writes": ["out/a.txt", "out/b.txt"],
            },
            "risk": "medium",
            "budget_hint": {"model_calls": 2, "tool_budget_units": 0},
            "evidence_refs": [],
        },
    }
    task = {
        "task_id": "task-parent",
        "parallel_safety": "disjoint_writes",
        "write_scope": ["out/a.txt", "out/b.txt"],
        "multi_agent_strategy": {
            "mode": "disjoint_write_workers",
            "max_child_workers": 2,
            "coordination_policy": {"requires_disjoint_write_scope": True},
        },
    }
    default_plan = build_subagent_child_plan(
        decision=decision,
        execution_result={"worker_invocation_id": "worker-0001"},
        task=task,
    )
    probe_plan = build_subagent_child_plan(
        decision=decision,
        execution_result={"worker_invocation_id": "worker-0001"},
        task=task,
        policy=with_maintainer_probe_policy({}),
    )
    assert len(default_plan["child_tasks"]) == 2
    default_exec = plan_swarm_execution(default_plan, policy={"feature_flags": {}})
    probe_exec = plan_swarm_execution(
        probe_plan,
        policy=with_maintainer_probe_policy({}),
    )
    assert default_exec.spawn_plan.scheduling_mode == "fake_serial"
    assert default_exec.spawn_plan.fake_path is True
    assert probe_exec.spawn_plan.scheduling_mode == "parallel"
    assert probe_exec.spawn_plan.fake_path is False


def test_execute_subagent_path_persists_swarm_execution_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeSubagentExecuteClient()

    ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    swarm_path = run_dir / "swarm_execution_plans.jsonl"
    assert swarm_path.exists(), "execute subagent path must persist swarm_execution_plans.jsonl"
    records = [json.loads(line) for line in swarm_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) >= 1
    latest = records[-1]
    assert latest["subagent_child_plan_id"]
    assert latest["scheduling_mode"] in {"serial", "fake_serial", "parallel"}
    assert "fake_path" in latest

    child_plans_path = run_dir / "subagent_child_plans.jsonl"
    assert child_plans_path.exists(), "execute subagent path must persist subagent_child_plans.jsonl"
    child_plans = [
        json.loads(line) for line in child_plans_path.read_text(encoding="utf-8").splitlines()
    ]
    assert child_plans[-1]["subagent_child_plan_id"] == latest["subagent_child_plan_id"]
