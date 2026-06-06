from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.agent_loop_executor import (
    build_agent_loop_execution_result,
    persist_subagent_child_plan_for_execution,
)
from asteria_runtime.core.swarm_scenario_audit import SwarmScenarioAuditor
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_execute_command import FakeDisjointWriteExecuteClient, FakePlanClient
from tests.integration.test_swarm_agent_loop_integration import _disjoint_task, _subagent_decision


GATE = json.loads(Path("benchmarks/phase5d_swarm_scenario_gate.json").read_text(encoding="utf-8"))
SCENARIO = json.loads(Path("benchmarks/phase5_swarm_scenario.json").read_text(encoding="utf-8"))


def test_phase5d_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "5"
    assert Path(GATE["scenario"]).exists()
    assert Path(GATE["maintainer_script"]).exists()
    assert Path(GATE["plan"]).exists()
    for dep in GATE["depends_on_gates"]:
        assert Path(dep).exists()
    matrix = json.loads(Path("benchmarks/runtime_validation_matrix.json").read_text(encoding="utf-8"))
    case_ids = [item["id"] for item in matrix.get("cases", [])]
    assert GATE["validation_matrix_case"] in case_ids


def test_execute_parallel_disjoint_passes_scenario_audit(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "write two independent outputs", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    base = {
        "schema_version": "0.1.0",
        "description": "Write an independent output file.",
        "status": "ready",
        "priority": "medium",
        "role": "CoderAgent",
        "depends_on": [],
        "acceptance": ["output file exists"],
        "allowed_tools": ["write_file", "run_command"],
        "expected_artifacts": [],
        "task_kind": "implementation",
        "parallel_safety": "disjoint_writes",
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
        "created_at": "2026-06-06T12:00:00+08:00",
        "updated_at": "2026-06-06T12:00:00+08:00",
        "notes": "",
    }
    task_plan["tasks"] = [
        {
            **base,
            "task_id": "task-0001",
            "title": "Write alpha",
            "write_scope": ["out/alpha.txt"],
            "expected_changed_files": ["out/alpha.txt"],
        },
        {
            **base,
            "task_id": "task-0002",
            "title": "Write beta",
            "write_scope": ["out/beta.txt"],
            "expected_changed_files": ["out/beta.txt"],
        },
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        max_tasks=2,
        model_client=FakeDisjointWriteExecuteClient(),
        parallel_writes=True,
    ).run()

    validator = SchemaValidator(Path("schemas"))
    audit = SwarmScenarioAuditor(validator).evaluate_run_dir(run_dir)
    assert audit.ok is True
    assert "execute_parallel_disjoint" in audit.detected_paths


def test_subagent_path_passes_scenario_audit(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / "run-subagent-exec"
    run_dir.mkdir()
    decision = _subagent_decision()
    execution = build_agent_loop_execution_result(decision)
    execution["worker_invocation_id"] = "worker-disjoint-0001"
    execution["worker_result_id"] = "worker-result-disjoint-0001"
    execution["runtime_profile_id"] = "runtime-profile-disjoint-0001"
    persist_subagent_child_plan_for_execution(
        run_dir=run_dir,
        validator=validator,
        decision=decision,
        execution_result=execution,
        task=_disjoint_task(),
    )
    audit = SwarmScenarioAuditor(validator).evaluate_run_dir(run_dir)
    assert audit.ok is True
    assert "subagent_swarm_planning" in audit.detected_paths
    assert SCENARIO["paths"]["subagent_swarm_planning"]["min_swarm_plans"] == 1
