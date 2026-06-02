from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.runtime_readiness_gate import runtime_readiness_gate
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def _loop_decision(action: str = "replan") -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": "agent-loop-decision-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "created_at": "2026-05-29T10:00:00+08:00",
        "next_action": {
            "action": action,
            "reason": "review timeout exposed a plan gap",
            "target_task_id": "task-1",
            "capability_ref": {
                "type": "subagent" if action == "subagent" else "runtime",
                "name": "subagent" if action == "subagent" else "recovery-review",
            },
            "expected_observation": {"summary": "replan command is available"},
            "risk": "medium",
            "budget_hint": {"model_calls": 1},
            "evidence_refs": ["model_calls.jsonl"],
        },
    }


def _loop_execution(action: str = "replan") -> dict:
    return {
        "schema_version": "0.1.0",
        "execution_id": "agent-loop-execution-0001",
        "decision_id": "agent-loop-decision-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "target_task_id": "task-1",
        "created_at": "2026-05-29T10:00:01+08:00",
        "action": action,
        "status": "dispatched",
        "target": "replan_command",
        "recommended_command": "replan",
        "capability_ref": {
            "type": "subagent" if action == "subagent" else "runtime",
            "name": "subagent" if action == "subagent" else "recovery-review",
        },
        "reason": "review timeout exposed a plan gap",
        "expected_observation": {"summary": "replan command is available"},
        "risk": "medium",
        "budget_hint": {"model_calls": 1},
        "evidence_refs": ["model_calls.jsonl"],
    }


def _loop_observation(
    *,
    action: str = "replan",
    status: str = "pending",
    decision_id: str = "agent-loop-decision-0001",
    execution_id: str = "agent-loop-execution-0001",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "observation_id": "agent-loop-observation-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "target_task_id": "task-1",
        "created_at": "2026-05-29T10:00:02+08:00",
        "observation_type": {
            "tool": "tool_result",
            "subagent": "subagent_result",
            "repair": "repair_result",
            "replan": "replan_result",
            "ask": "decision_pending",
            "stop": "stop_report",
        }[action],
        "source_execution_id": execution_id,
        "source_decision_id": decision_id,
        "status": status,
        "summary": f"{action} observation is {status}.",
        "evidence_refs": ["agent_loop_execution_results.jsonl"],
        "next_recommended_action": "repair" if status == "failed" else None,
    }


def _worker_invocation() -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_invocation_id": "worker-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "agent_id": "subagent",
        "runtime_profile_id": "runtime-profile-subagent-subagent",
        "status": "queued",
        "started_at": "2026-05-29T10:00:01+08:00",
        "ended_at": None,
        "summary": "Dispatch task-1 to subagent.",
        "parent_worker_invocation_id": "worker-0000",
        "parent_task_id": "task-parent",
        "worker_kind": "subagent",
        "parallel_safety": "serial",
    }


def _worker_result(status: str = "partial") -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_result_id": "worker-result-0001",
        "worker_invocation_id": "worker-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "status": status,
        "artifact_refs": [],
        "validation_refs": [],
        "failure_evidence_refs": [],
        "cost": {"model_calls": 0, "tool_calls": 0},
        "summary": "Subagent dispatch recorded.",
    }


def _task_execution_evidence(
    *,
    status: str = "done",
    created_at: str = "2026-05-29T10:00:04+08:00",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "evidence_id": "task-execution-0001",
        "run_id": "run-1",
        "task_id": "task-1",
        "status": status,
        "summary": "Task recovered after failed observation.",
        "task": {"task_id": "task-1"},
        "action": {},
        "candidate": {},
        "contract_check": {"ok": status == "done"},
        "tool_results": [],
        "verification_results": [],
        "created_at": created_at,
    }


def _context_budget_snapshot(
    *,
    pressure_status: str = "within_budget",
    ratio: float = 0.1,
    duplicate_tokens: int = 0,
    snapshot_id: str = "context-budget-snapshot-0001",
    task_id: str = "task-1",
    runtime_profile_id: str = "runtime-profile-subagent-subagent",
    parent_worker_invocation_id: str = "worker-0001",
    worker_kind: str = "subagent",
    scope: str = "subagent_child",
) -> dict:
    boundary = "not_required"
    if pressure_status in {"hard_stop", "exceeded"}:
        boundary = "required"
    elif pressure_status == "near_limit":
        boundary = "recommended"
    elif duplicate_tokens:
        boundary = "dedupe_recommended"
    return {
        "schema_version": "0.1.0",
        "snapshot_id": snapshot_id,
        "run_id": "run-1",
        "task_id": task_id,
        "created_at": "2026-05-29T10:00:03+08:00",
        "scope": scope,
        "runtime_profile_id": runtime_profile_id,
        "context_mount_id": "context-worker-0001",
        "worker_kind": worker_kind,
        "isolation_policy": "subagent_child_context",
        "parent_worker_invocation_id": parent_worker_invocation_id,
        "parent_runtime_profile_id": "runtime-profile-worker-0001",
        "estimated_tokens": 1000,
        "sections": {"task_brief": 100, "subagent_worker": 50},
        "duplicate_content_hashes": ["abc123"] if duplicate_tokens else [],
        "duplicate_estimated_tokens": duplicate_tokens,
        "duplicate_ref_count": 1 if duplicate_tokens else 0,
        "context_window_tokens": 10000,
        "context_window_ratio": ratio,
        "pressure_status": pressure_status,
        "compaction_threshold": 0.75,
        "hard_stop_threshold": 0.9,
        "compact_boundary": {
            "status": boundary,
            "recommended_action": "continue",
            "estimated_tokens_before": 1000,
            "estimated_duplicate_tokens": duplicate_tokens,
            "preserve_sections": ["task_brief"],
            "droppable_sections": [],
        },
        "evidence_refs": ["context_envelopes/context_envelope_task-1.json"],
    }


def _runtime_profile(runtime_profile_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "runtime_profile_id": runtime_profile_id,
        "agent_id": "subagent",
        "model_profile_id": f"model-{runtime_profile_id}",
        "tool_permission_profile_id": f"tools-{runtime_profile_id}",
        "sandbox_profile_id": f"sandbox-{runtime_profile_id}",
        "context_mount_id": f"context-{runtime_profile_id}",
        "budget": {"max_model_calls": 1, "max_tool_calls": 4},
    }


def _readonly_child_worker(
    *,
    worker_id: str,
    task_id: str,
    runtime_profile_id: str,
    parent_worker_id: str = "worker-0001",
    parallel_safety: str = "readonly",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_invocation_id": worker_id,
        "run_id": "run-1",
        "task_id": task_id,
        "agent_id": "subagent",
        "runtime_profile_id": runtime_profile_id,
        "status": "succeeded",
        "started_at": "2026-05-29T10:00:04+08:00",
        "ended_at": "2026-05-29T10:00:05+08:00",
        "summary": f"Readonly child {task_id} completed.",
        "parent_worker_invocation_id": parent_worker_id,
        "parent_task_id": "task-1",
        "worker_kind": "subagent_readonly_child",
        "parallel_safety": parallel_safety,
        "child_plan_refs": ["subagent-child-plan-0001"],
    }


def _readonly_child_result(
    *,
    worker_id: str,
    result_id: str,
    task_id: str,
    status: str = "succeeded",
    validation_refs: list[str] | None = None,
    summary: str | None = None,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "worker_result_id": result_id,
        "worker_invocation_id": worker_id,
        "run_id": "run-1",
        "task_id": task_id,
        "status": status,
        "artifact_refs": [],
        "validation_refs": validation_refs if validation_refs is not None else [f"{task_id}/verify.json"],
        "failure_evidence_refs": [] if status == "succeeded" else [f"{task_id}/failure.json"],
        "cost": {"model_calls": 1, "tool_calls": 2},
        "summary": summary or f"Readonly child {task_id} result.",
        "parent_worker_invocation_id": "worker-0001",
        "worker_kind": "subagent_readonly_child",
        "child_plan_refs": ["subagent-child-plan-0001"],
    }


def _readonly_fanout_plan(*, write_tool: bool = False) -> dict:
    allowed_tools = ["list_files", "read_file", "search_text"]
    if write_tool:
        allowed_tools = [*allowed_tools, "write_file"]
    children = []
    for index in (1, 2):
        children.append(
            {
                "child_task_id": f"task-1-child-{index:02d}",
                "task_id": "task-1",
                "title": f"Inspect shard {index}",
                "objective": f"Read shard {index}.",
                "acceptance": [f"shard {index} inspected"],
                "read_scope": ["."],
                "write_scope": [],
                "allowed_tools": allowed_tools,
                "depends_on": [],
                "risk": "low",
                "parallel_safety": "readonly",
                "worker_role": "research_child",
                "write_allowed": False,
                "expected_output": ["validation refs"],
                "verification_expectation": {"requires_verification": True},
            }
        )
    return {
        "schema_version": "0.1.0",
        "subagent_child_plan_id": "subagent-child-plan-0001",
        "run_id": "run-1",
        "parent_task_id": "task-parent",
        "target_task_id": "task-1",
        "parent_decision_id": "agent-loop-decision-0001",
        "parent_execution_id": "agent-loop-execution-0001",
        "worker_invocation_id": "worker-0001",
        "worker_result_id": "worker-result-0001",
        "runtime_profile_id": "runtime-profile-subagent-subagent",
        "planner_id": "RuntimeSubagentPlanner",
        "decomposition_strategy": "readonly_fanout",
        "scheduling_strategy": "parallel_readonly_safe",
        "max_child_workers": 2,
        "coordination_policy": {"write_allowed": False, "requires_merge_gate": False},
        "status": "planned",
        "parallel_safety": "readonly",
        "child_tasks": children,
        "evidence_refs": ["agent_loop_execution_results.jsonl"],
        "created_at": "2026-05-29T10:00:03+08:00",
    }


def _disjoint_write_plan(*, overlapping: bool = False) -> dict:
    scopes = [["docs/a.md"], ["docs/a.md" if overlapping else "docs/b.md"]]
    children = []
    for index, scope in enumerate(scopes, start=1):
        children.append(
            {
                "child_task_id": f"task-1-write-{index:02d}",
                "task_id": "task-1",
                "title": f"Write shard {index}",
                "objective": f"Write shard {index}.",
                "acceptance": [f"shard {index} written"],
                "read_scope": ["."],
                "write_scope": scope,
                "allowed_tools": ["write_file", "run_command"],
                "depends_on": [],
                "risk": "medium",
                "parallel_safety": "disjoint_writes",
                "worker_role": "implementation_child",
                "write_allowed": True,
                "expected_output": scope,
                "verification_expectation": {"requires_verification": True},
            }
        )
    return {
        "schema_version": "0.1.0",
        "subagent_child_plan_id": "subagent-child-plan-0002",
        "run_id": "run-1",
        "parent_task_id": "task-parent",
        "target_task_id": "task-1",
        "parent_decision_id": "agent-loop-decision-0001",
        "parent_execution_id": "agent-loop-execution-0001",
        "worker_invocation_id": "worker-0001",
        "worker_result_id": "worker-result-0001",
        "runtime_profile_id": "runtime-profile-subagent-subagent",
        "planner_id": "RuntimeSubagentPlanner",
        "decomposition_strategy": "disjoint_write_child_tasks",
        "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
        "max_child_workers": 2,
        "coordination_policy": {
            "write_allowed": True,
            "requires_merge_gate": True,
            "requires_disjoint_write_scope": True,
        },
        "status": "planned",
        "parallel_safety": "disjoint_writes",
        "child_tasks": children,
        "evidence_refs": ["agent_loop_execution_results.jsonl"],
        "created_at": "2026-05-29T10:00:04+08:00",
    }


def _candidate_promotion(
    status: str = "pending_manual_approval",
    merge_ok: bool = True,
    *,
    task_id: str = "task-1",
    candidate_id: str = "candidate-0001",
    workspace: str = "cw/0001",
    promotable_files: list[str] | None = None,
    promoted_files: list[str] | None = None,
) -> dict:
    promotable_files = promotable_files or ["src/a.py"]
    return {
        "schema_version": "0.1.0",
        "promotion_id": f"promotion-{candidate_id}",
        "run_id": "run-1",
        "task_id": task_id,
        "candidate_id": candidate_id,
        "workspace": workspace,
        "strategy": "temp_workspace",
        "workspace_policy": "isolated_copy",
        "backend_reason": "test",
        "branch_name": None,
        "promotable_files": promotable_files,
        "promoted_files": promoted_files
        if promoted_files is not None
        else ([] if status != "promoted" else promotable_files),
        "status": status,
        "approval_mode": "manual",
        "merge_gate": {
            "ok": merge_ok,
            "promotable_files": promotable_files if merge_ok else [],
            "violations": [] if merge_ok else ["changed files outside write_scope: src/a.py"],
        },
        "failure": None
        if status not in {"blocked", "promotion_failed"}
        else {"type": status, "message": "promotion could not be applied"},
        "decision": None,
        "created_at": "2026-05-29T10:00:03+08:00",
        "updated_at": "2026-05-29T10:00:04+08:00",
    }


def _append_ready_readonly_fanout(run_dir: Path, validator: SchemaValidator) -> None:
    JsonlStore(validator).append(run_dir / "workers.jsonl", _worker_invocation(), "worker_invocation")
    JsonlStore(validator).append(
        run_dir / "context_budget_snapshots.jsonl",
        _context_budget_snapshot(),
        "context_budget_snapshot",
    )
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _readonly_fanout_plan(),
        "subagent_child_plan",
    )
    for index in (1, 2):
        task_id = f"task-1-child-{index:02d}"
        worker_id = f"worker-000{index + 1}"
        runtime_profile_id = f"runtime-profile-child-{index}"
        JsonlStore(validator).append(
            run_dir / "workers.jsonl",
            _readonly_child_worker(
                worker_id=worker_id,
                task_id=task_id,
                runtime_profile_id=runtime_profile_id,
            ),
            "worker_invocation",
        )
        JsonlStore(validator).append(
            run_dir / "worker_results.jsonl",
            _readonly_child_result(
                worker_id=worker_id,
                result_id=f"worker-result-000{index + 1}",
                task_id=task_id,
            ),
            "worker_result",
        )
        JsonlStore(validator).append(
            run_dir / "runtime_profiles.jsonl",
            _runtime_profile(runtime_profile_id),
            "runtime_profile",
        )
        JsonlStore(validator).append(
            run_dir / "context_budget_snapshots.jsonl",
            _context_budget_snapshot(
                snapshot_id=f"context-budget-snapshot-000{index + 1}",
                task_id=task_id,
                runtime_profile_id=runtime_profile_id,
                parent_worker_invocation_id="worker-0001",
                worker_kind="subagent_readonly_child",
            ),
            "context_budget_snapshot",
        )


def _write_readonly_write_gate_task_plan(run_dir: Path) -> None:
    (run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-1",
                        "runtime_profile_hints": {
                            "validation_probe_ids": ["readonly_write_tool_blocked"]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_runtime_readiness_gate_blocks_missing_loop_decision_for_failed_observation(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    (tmp_path / ".asteria" / "runs" / "run-1").mkdir(parents=True)

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={
            "failed_observation_count": 1,
            "recommended_route": "repair",
            "evidence_refs": ["tool_observations.jsonl"],
        },
    )

    assert gate["status"] == "blocked"
    observation = next(check for check in gate["checks"] if check["name"] == "observation_next_action")
    assert "AgentLoopDecision" in observation["summary"]


def test_runtime_readiness_gate_accepts_successful_task_execution_after_failed_plan(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "task_execution_evidence.jsonl",
        _task_execution_evidence(created_at="2026-05-29T10:00:06+08:00"),
        "task_execution_evidence",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={
            "run_id": "run-1",
            "task_id": "task-1",
            "created_at": "2026-05-29T10:00:02+08:00",
            "failed_observation_count": 1,
            "recommended_route": "repair",
            "evidence_refs": ["tool_observations.jsonl"],
        },
    )

    observation = next(check for check in gate["checks"] if check["name"] == "observation_next_action")
    assert observation["status"] == "ready"
    assert "successful task execution" in observation["summary"]


def test_runtime_readiness_gate_surfaces_recovery_loop_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("replan"),
        "agent_loop_decision",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        _loop_execution("replan"),
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="replan"),
        "agent_loop_observation",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={
            "run_id": "run-1",
            "task_id": "task-1",
            "failed_observation_count": 1,
            "recommended_route": "repair",
            "evidence_refs": ["tool_observations.jsonl"],
        },
    )

    observation = next(check for check in gate["checks"] if check["name"] == "observation_next_action")
    assert observation["status"] == "review"
    assert "explicit `replan` AgentLoopDecision" in observation["summary"]
    assert observation["recommended_action"] == (
        "Run `asteria replan` to continue the recorded recovery decision."
    )
    execution = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution["status"] == "ready"
    assert "replan_command" in execution["summary"]


def test_runtime_readiness_gate_blocks_loop_decision_without_runtime_execution(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("repair"),
        "agent_loop_decision",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution["status"] == "blocked"
    assert "no matching Runtime execution result" in execution["summary"]


def test_runtime_readiness_gate_matches_loop_execution_by_run_id(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    old_run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    latest_run_dir = tmp_path / ".asteria" / "runs" / "run-2"
    old_run_dir.mkdir(parents=True)
    latest_run_dir.mkdir(parents=True)
    old_execution = _loop_execution("repair")
    old_execution["created_at"] = "2026-05-29T12:00:00+08:00"
    JsonlStore(validator).append(
        old_run_dir / "agent_loop_execution_results.jsonl",
        old_execution,
        "agent_loop_execution_result",
    )
    latest_decision = _loop_decision("repair")
    latest_decision["run_id"] = "run-2"
    latest_decision["created_at"] = "2026-05-29T11:00:00+08:00"
    JsonlStore(validator).append(
        latest_run_dir / "agent_loop_decisions.jsonl",
        latest_decision,
        "agent_loop_decision",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution["status"] == "blocked"
    assert "no matching Runtime execution result" in execution["summary"]
    assert execution["evidence_refs"] == ["agent-loop-decision-0001"]


def test_runtime_readiness_gate_requires_subagent_worker_evidence(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("subagent"),
        "agent_loop_decision",
    )
    execution = _loop_execution("subagent")
    execution.update(
        {
            "target": "subagent_dispatcher",
            "recommended_command": "execute",
            "runtime_profile_id": "runtime-profile-subagent-subagent",
        }
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert "missing worker dispatch evidence" in execution_check["summary"]


def test_runtime_readiness_gate_accepts_subagent_worker_dispatch(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("subagent"),
        "agent_loop_decision",
    )
    execution = _loop_execution("subagent")
    execution.update(
        {
            "target": "subagent_dispatcher",
            "recommended_command": "execute",
            "worker_invocation_id": "worker-0001",
            "worker_result_id": "worker-result-0001",
            "runtime_profile_id": "runtime-profile-subagent-subagent",
            "worker_status": "partial",
        }
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(run_dir / "workers.jsonl", _worker_invocation(), "worker_invocation")
    JsonlStore(validator).append(
        run_dir / "worker_results.jsonl",
        _worker_result("partial"),
        "worker_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="subagent"),
        "agent_loop_observation",
    )
    JsonlStore(validator).append(
        run_dir / "context_budget_snapshots.jsonl",
        _context_budget_snapshot(),
        "context_budget_snapshot",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "ready"
    context_check = next(
        check for check in gate["checks"] if check["name"] == "subagent_context_isolation"
    )
    assert context_check["status"] == "ready"


def test_runtime_readiness_gate_accepts_readonly_fanout_child_evidence(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_ready_readonly_fanout(run_dir, validator)

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "ready"
    assert "2/2 child worker" in fanout["summary"]
    assert "model_calls=2" in fanout["summary"]


def test_runtime_readiness_gate_scopes_readonly_fanout_results_to_plan_run(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_ready_readonly_fanout(run_dir, validator)
    polluted_run_dir = tmp_path / ".asteria" / "runs" / "run-2"
    polluted_run_dir.mkdir(parents=True)
    for index in (1, 2):
        JsonlStore(validator).append(
            polluted_run_dir / "worker_results.jsonl",
            _readonly_child_result(
                worker_id=f"worker-000{index + 1}",
                result_id=f"worker-result-polluted-000{index + 1}",
                task_id=f"task-2-child-{index:02d}",
                status="denied",
                validation_refs=[],
                summary="Delegation brief quality gate blocked high-risk worker: allowed_writes",
            ),
            "worker_result",
        )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "ready"
    assert "2/2 child worker" in fanout["summary"]


def test_runtime_readiness_gate_accepts_readonly_fanout_task_context_snapshots(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_ready_readonly_fanout(run_dir, validator)
    path = run_dir / "context_budget_snapshots.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row.get("worker_kind") == "subagent_readonly_child":
            row["scope"] = "task_context"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "ready"


def test_runtime_readiness_gate_blocks_incomplete_readonly_fanout_result(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_ready_readonly_fanout(run_dir, validator)
    lines = (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    (run_dir / "worker_results.jsonl").write_text("\n".join(lines[:1]) + "\n", encoding="utf-8")

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "blocked"
    assert "execution evidence is incomplete" in fanout["summary"]
    assert "worker-0003" in fanout["summary"]


def test_runtime_readiness_gate_accepts_expected_readonly_write_gate_probe_failure(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_ready_readonly_fanout(run_dir, validator)
    _write_readonly_write_gate_task_plan(run_dir)
    lines = []
    for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item.get("worker_kind") == "subagent_readonly_child":
            item["status"] = "failed"
            item["summary"] = (
                "Readonly fanout child cannot use write tool: " + str(item.get("task_id"))
            )
            item["validation_refs"] = []
        lines.append(json.dumps(item))
    (run_dir / "worker_results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "ready"
    assert "Readonly write-gate probe" in fanout["summary"]


def test_runtime_readiness_gate_blocks_readonly_fanout_write_boundary(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _readonly_fanout_plan(write_tool=True),
        "subagent_child_plan",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    fanout = next(check for check in gate["checks"] if check["name"] == "subagent_readonly_fanout")
    assert fanout["status"] == "blocked"
    assert "exposes write tools" in fanout["summary"]


def test_runtime_readiness_gate_reviews_pending_candidate_promotion(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        _candidate_promotion("pending_manual_approval", merge_ok=True),
        "candidate_promotion",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    promotion = next(check for check in gate["checks"] if check["name"] == "candidate_promotion_safety")
    assert gate["status"] == "review"
    assert promotion["status"] == "review"
    assert "unresolved promotion" in promotion["summary"]


def test_runtime_readiness_gate_blocks_candidate_merge_gate_failure(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        _candidate_promotion("pending_manual_approval", merge_ok=False),
        "candidate_promotion",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    promotion = next(check for check in gate["checks"] if check["name"] == "candidate_promotion_safety")
    assert gate["status"] == "blocked"
    assert promotion["status"] == "blocked"
    assert "merge gate blocked" in promotion["summary"]
    assert "outside write_scope" in promotion["summary"]


def test_runtime_readiness_gate_accepts_discarded_candidate_recovery(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        _candidate_promotion("discarded", merge_ok=True),
        "candidate_promotion",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    promotion = next(check for check in gate["checks"] if check["name"] == "candidate_promotion_safety")
    assert promotion["status"] == "ready"
    assert "recovery action" in promotion["summary"]


def test_runtime_readiness_gate_accepts_disjoint_write_child_plan_gate(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _disjoint_write_plan(),
        "subagent_child_plan",
    )
    for index in (1, 2):
        JsonlStore(validator).append(
            run_dir / "candidate_promotions.jsonl",
            _candidate_promotion(
                "promoted",
                task_id=f"task-1-write-{index:02d}",
                candidate_id=f"candidate-000{index}",
                workspace=f"cw/000{index}",
                promotable_files=[f"docs/{'a' if index == 1 else 'b'}.md"],
            ),
            "candidate_promotion",
        )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    disjoint = next(check for check in gate["checks"] if check["name"] == "subagent_disjoint_write_gate")
    assert disjoint["status"] == "ready"
    assert "allows 2 child" in disjoint["summary"]


def test_runtime_readiness_gate_blocks_disjoint_write_plan_without_candidate_evidence(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _disjoint_write_plan(),
        "subagent_child_plan",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    disjoint = next(check for check in gate["checks"] if check["name"] == "subagent_disjoint_write_gate")
    assert disjoint["status"] == "ready"
    assert "blocked unsafe scheduling as expected" in disjoint["summary"]
    assert "candidate promotion evidence is required" in disjoint["summary"]


def test_runtime_readiness_gate_blocks_disjoint_write_plan_failed_merge_gate(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _disjoint_write_plan(),
        "subagent_child_plan",
    )
    for index in (1, 2):
        JsonlStore(validator).append(
            run_dir / "candidate_promotions.jsonl",
            _candidate_promotion(
                "promoted",
                merge_ok=index == 2,
                task_id=f"task-1-write-{index:02d}",
                candidate_id=f"candidate-000{index}",
                workspace=f"cw/000{index}",
                promotable_files=[f"docs/{'a' if index == 1 else 'b'}.md"],
            ),
            "candidate_promotion",
        )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    disjoint = next(check for check in gate["checks"] if check["name"] == "subagent_disjoint_write_gate")
    assert gate["status"] == "blocked"
    assert disjoint["status"] == "ready"
    assert "merge gate must pass" in disjoint["summary"]


def test_runtime_readiness_gate_blocks_overlapping_disjoint_write_child_plan(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        _disjoint_write_plan(overlapping=True),
        "subagent_child_plan",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    disjoint = next(check for check in gate["checks"] if check["name"] == "subagent_disjoint_write_gate")
    assert disjoint["status"] == "ready"
    assert "write_scope overlaps" in disjoint["summary"]


def test_runtime_readiness_gate_reviews_missing_subagent_context_snapshot(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(run_dir / "workers.jsonl", _worker_invocation(), "worker_invocation")

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    context_check = next(
        check for check in gate["checks"] if check["name"] == "subagent_context_isolation"
    )
    assert context_check["status"] == "review"
    assert "ContextBudgetMeter v2" in context_check["summary"]


def test_runtime_readiness_gate_blocks_subagent_context_hard_stop(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(run_dir / "workers.jsonl", _worker_invocation(), "worker_invocation")
    JsonlStore(validator).append(
        run_dir / "context_budget_snapshots.jsonl",
        _context_budget_snapshot(pressure_status="hard_stop", ratio=0.92),
        "context_budget_snapshot",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    context_check = next(
        check for check in gate["checks"] if check["name"] == "subagent_context_isolation"
    )
    assert context_check["status"] == "blocked"
    assert "compact hard-stop" in context_check["summary"]


def test_runtime_readiness_gate_blocks_execution_without_observation(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("replan"),
        "agent_loop_decision",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        _loop_execution("replan"),
        "agent_loop_execution_result",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "blocked"
    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert "no matching AgentLoopObservation" in execution_check["summary"]


def test_runtime_readiness_gate_blocks_failed_observation_without_recovery_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    JsonlStore(validator).append(
        run_dir / "agent_loop_decisions.jsonl",
        _loop_decision("tool"),
        "agent_loop_decision",
    )
    execution = _loop_execution("tool")
    execution["target"] = "tool_gateway"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="tool", status="failed"),
        "agent_loop_observation",
    )
    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "blocked"
    assert "no follow-up AgentLoopDecision" in execution_check["summary"]


def test_runtime_readiness_gate_accepts_failed_observation_with_recovery_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    tool_decision = _loop_decision("tool")
    tool_decision["decision_id"] = "agent-loop-decision-0001"
    repair_decision = _loop_decision("repair")
    repair_decision["decision_id"] = "agent-loop-decision-0002"
    repair_decision["created_at"] = "2026-05-29T10:00:03+08:00"
    JsonlStore(validator).append(run_dir / "agent_loop_decisions.jsonl", tool_decision, "agent_loop_decision")
    JsonlStore(validator).append(run_dir / "agent_loop_decisions.jsonl", repair_decision, "agent_loop_decision")
    tool_execution = _loop_execution("tool")
    tool_execution["target"] = "tool_gateway"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        tool_execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(action="tool", status="failed"),
        "agent_loop_observation",
    )
    repair_execution = _loop_execution("repair")
    repair_execution["execution_id"] = "agent-loop-execution-0002"
    repair_execution["decision_id"] = "agent-loop-decision-0002"
    repair_execution["target"] = "debug_agent"
    repair_execution["recommended_command"] = "debug"
    JsonlStore(validator).append(
        run_dir / "agent_loop_execution_results.jsonl",
        repair_execution,
        "agent_loop_execution_result",
    )
    JsonlStore(validator).append(
        run_dir / "agent_loop_observations.jsonl",
        _loop_observation(
            action="repair",
            decision_id="agent-loop-decision-0002",
            execution_id="agent-loop-execution-0002",
        ),
        "agent_loop_observation",
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    execution_check = next(check for check in gate["checks"] if check["name"] == "agent_loop_execution")
    assert execution_check["status"] == "ready"
    assert "debug_agent" in execution_check["summary"]


def test_runtime_readiness_gate_reviews_capability_mismatch(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "tool",
                                    "name": "read_file",
                                    "selection_state": "selected",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        run_dir / "capability_decisions.jsonl",
        {
            "capability_type": "tool",
            "capability": "run_command",
            "decision": {"decision": "allow"},
        },
        None,
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    assert gate["status"] == "review"
    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "review"
    assert "not fully aligned" in capability["summary"]


def test_runtime_readiness_gate_explains_visible_unselected_capability(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "mcp",
                                    "name": "runtime_matrix/echo",
                                    "visible": True,
                                    "selection_state": "skipped",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        run_dir / "capability_decisions.jsonl",
        {
            "capability_type": "mcp",
            "capability": "runtime_matrix/echo",
            "decision": {"decision": "allow"},
        },
        None,
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "review"
    assert "visible but not selected" in capability["summary"]


def test_runtime_readiness_gate_matches_mcp_server_catalog_to_tool_invocation(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "mcp",
                                    "name": "runtime_matrix",
                                    "visible": True,
                                    "selection_state": "selected",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        run_dir / "capability_decisions.jsonl",
        {
            "capability_type": "mcp",
            "capability": "runtime_matrix/echo",
            "decision": {"decision": "allow"},
        },
        None,
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "ready"


def test_runtime_readiness_gate_normalizes_prefixed_capability_decision(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "mcp",
                                    "name": "runtime_matrix/echo",
                                    "visible": True,
                                    "selection_state": "selected",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        run_dir / "capability_decisions.jsonl",
        {
            "capability_type": "mcp",
            "capability": "mcp:runtime_matrix/echo",
            "decision": {"decision": "allow"},
        },
        None,
    )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "ready"


def test_runtime_readiness_gate_uses_task_plan_allowed_tools_as_catalog_fallback(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "task_plan.json").write_text(
        json.dumps({"tasks": [{"allowed_tools": ["write_file", "run_command"]}]}),
        encoding="utf-8",
    )
    for capability in ("write_file", "run_command"):
        JsonlStore(validator).append(
            run_dir / "capability_decisions.jsonl",
            {
                "capability_type": "tool",
                "capability": capability,
                "decision": {"decision": "ask", "allowed": True},
            },
            None,
        )

    gate = runtime_readiness_gate(
        root=tmp_path,
        validator=validator,
        model_call_contract={"status": "healthy"},
        context_pressure_summary={"max_context_window_ratio": 0.1},
        latest_observation_plan={},
    )

    capability = next(check for check in gate["checks"] if check["name"] == "capability_selection")
    assert capability["status"] == "ready"
