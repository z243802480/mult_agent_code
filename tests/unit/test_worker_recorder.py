from pathlib import Path

from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_worker_recorder_persists_invocation_result_and_event(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )
    recorder = WorkerExecutionRecorder(validator)

    recorder.record_execution(
        context=context,
        worker_id="worker-0001",
        result_id="worker-result-0001",
        task={
            "task_id": "task-0001",
            "role": "CoderAgent",
            "title": "Write scoped artifact",
            "description": "Create the requested scoped artifact.",
            "acceptance": ["artifact exists"],
            "read_scope": ["src/"],
            "write_scope": ["out/result.txt"],
            "expected_artifacts": ["out/result.txt"],
            "validation_commands": ["pytest"],
            "allowed_tools": ["write_file", "run_command"],
            "parallel_safety": "serial",
            "merge_strategy": "copy",
            "verification_policy": {"required": True},
            "completion_contract": {"requires_verification": True},
        },
        status="succeeded",
        started_at="2026-05-14T10:00:00+08:00",
        ended_at="2026-05-14T10:00:05+08:00",
        model_calls=1,
        tool_calls=2,
        artifact_refs=["artifact-0001"],
        validation_refs=["validation-0001"],
        failure_evidence_refs=[],
        summary="done",
        runtime_profile_id="runtime-profile-0001",
        actor="WorkerRecorderTest",
    )

    jsonl = JsonlStore(validator)
    workers = jsonl.read_all(tmp_path / "workers.jsonl", "worker_invocation")
    results = jsonl.read_all(tmp_path / "worker_results.jsonl", "worker_result")
    events = jsonl.read_all(tmp_path / "events.jsonl", "event")
    assert workers[0]["worker_invocation_id"] == "worker-0001"
    assert workers[0]["status"] == "succeeded"
    assert workers[0]["delegation_brief"]["goal"] == "Write scoped artifact"
    assert workers[0]["delegation_brief"]["allowed_writes"] == ["out/result.txt"]
    assert workers[0]["brief_quality"]["status"] == "pass"
    assert results[0]["worker_result_id"] == "worker-result-0001"
    assert results[0]["status"] == "succeeded"
    assert results[0]["cost"] == {"model_calls": 1, "tool_calls": 2}
    graph = JsonStore(validator).read(tmp_path / "agent_run_graph.json", "agent_run_graph")
    assert graph["collaboration_summary"]["total_workers"] == 1
    assert graph["collaboration_summary"]["strategy_modes"] == []
    assert graph["collaboration_summary"]["candidate_workspace_count"] == 0
    assert graph["collaboration_summary"]["promotion_queue_total"] == 0
    assert graph["collaboration_summary"]["merge_gate_block_count"] == 0
    assert graph["collaboration_summary"]["collaboration_protocol"] == {
        "isolation_model": "candidate_workspace_per_write_worker",
        "review_agent_role": "summarize_child_diffs_conflicts_and_release_risks",
        "debug_agent_role": "retry_or_replace_failed_child_worker_from_evidence",
        "merge_gate_role": "block_scope_conflicts_and_failed_validation_before_promotion",
        "promotion_queue_role": "centralize_manual_approval_retry_reject_or_discard",
    }
    assert graph["child_worker_plans"][0]["budget"] == {
        "max_model_calls": 1,
        "max_tool_calls": 1,
    }
    assert events[-1]["type"] == "worker_recorded"
    assert events[-1]["actor"] == "WorkerRecorderTest"


def test_agent_run_graph_links_candidate_workspace_promotion_and_merge_gate(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "candidate-0001.json").write_text(
        """
{
  "schema_version": "0.1.0",
  "candidate_id": "candidate-0001",
  "task_id": "task-0001",
  "workspace": "cw/0001",
  "strategy": "temp_workspace",
  "workspace_policy": "isolated_copy",
  "backend_reason": "test",
  "branch_name": null,
  "status": "active",
  "parent_worker_invocation_id": "worker-0001",
  "parent_runtime_profile_id": "runtime-profile-0001",
  "worker_kind": "subagent_disjoint_write_child",
  "parallel_safety": "disjoint_writes"
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        tmp_path / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": "cw/0001",
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["src/a.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {
                "ok": False,
                "promotable_files": [],
                "violations": ["changed files outside write_scope: src/a.py"],
            },
            "failure": None,
            "decision": None,
            "created_at": "2026-05-29T10:00:00+08:00",
            "updated_at": "2026-05-29T10:00:01+08:00",
        },
        "candidate_promotion",
    )

    graph = AgentRunGraphBuilder(validator).build(tmp_path, run_id="run-1")

    assert graph["candidate_workspaces"][0]["candidate_id"] == "candidate-0001"
    assert graph["candidate_workspaces"][0]["promotion_ids"] == ["promotion-0001"]
    assert graph["promotion_queue"][0]["merge_gate_ok"] is False
    assert graph["merge_gate_summary"]["blocked_count"] == 1
    assert graph["collaboration_summary"]["candidate_workspace_count"] == 1
    assert graph["collaboration_summary"]["promotion_pending_count"] == 1
    assert graph["collaboration_summary"]["merge_gate_block_count"] == 1
    assert any(
        "Resolve merge gate blockers" in action
        for action in graph["collaboration_summary"]["next_actions"]
    )


def test_agent_run_graph_marks_discarded_promotion_as_recovered(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "candidate-0001.json").write_text(
        """
{
  "schema_version": "0.1.0",
  "candidate_id": "candidate-0001",
  "task_id": "task-0001",
  "workspace": "cw/0001",
  "strategy": "temp_workspace",
  "workspace_policy": "isolated_copy",
  "backend_reason": "test",
  "branch_name": null,
  "status": "discarded"
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    JsonlStore(validator).append(
        tmp_path / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": "cw/0001",
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["src/a.py"],
            "promoted_files": [],
            "status": "discarded",
            "approval_mode": "manual",
            "merge_gate": {"ok": False, "violations": ["outside scope"]},
            "failure": None,
            "decision": {
                "actor": "cli",
                "action": "discard",
                "reason": "discard blocked candidate",
                "decided_at": "2026-05-29T10:00:02+08:00",
            },
            "created_at": "2026-05-29T10:00:00+08:00",
            "updated_at": "2026-05-29T10:00:03+08:00",
        },
        "candidate_promotion",
    )

    graph = AgentRunGraphBuilder(validator).build(tmp_path, run_id="run-1")

    assert graph["promotion_queue"][0]["recovery_action"] == "discard"
    assert graph["promotion_queue"][0]["recovery_status"] == "recovered"
    assert graph["promotion_recovery_summary"]["recovered_count"] == 1
    assert graph["promotion_recovery_summary"]["discarded_candidate_count"] == 1
    assert graph["collaboration_summary"]["promotion_recovered_count"] == 1
    assert graph["collaboration_summary"]["promotion_recovery_unresolved_count"] == 0


def test_agent_run_graph_links_child_worker_to_subagent_child_plan_ref(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    jsonl = JsonlStore(validator)
    for worker in [
        {
            "schema_version": "0.1.0",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "agent_id": "subagent",
            "runtime_profile_id": "runtime-profile-parent",
            "status": "succeeded",
            "started_at": "2026-05-29T10:00:00+08:00",
            "ended_at": "2026-05-29T10:00:01+08:00",
            "summary": "Parent subagent planned readonly fanout.",
            "worker_kind": "subagent",
            "parallel_safety": "serial",
        },
        {
            "schema_version": "0.1.0",
            "worker_invocation_id": "worker-0002",
            "run_id": "run-1",
            "task_id": "task-0001-child-01",
            "agent_id": "subagent",
            "runtime_profile_id": "runtime-profile-child",
            "status": "succeeded",
            "started_at": "2026-05-29T10:00:02+08:00",
            "ended_at": "2026-05-29T10:00:03+08:00",
            "summary": "Readonly child inspected shard.",
            "parent_worker_invocation_id": "worker-0001",
            "parent_task_id": "task-0001",
            "worker_kind": "subagent_readonly_child",
            "parallel_safety": "readonly",
            "child_plan_refs": ["subagent-child-plan-0001"],
        },
    ]:
        jsonl.append(tmp_path / "workers.jsonl", worker, "worker_invocation")
    jsonl.append(
        tmp_path / "worker_results.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_result_id": "worker-result-0002",
            "worker_invocation_id": "worker-0002",
            "run_id": "run-1",
            "task_id": "task-0001-child-01",
            "status": "succeeded",
            "artifact_refs": [],
            "validation_refs": ["validation-child-01"],
            "failure_evidence_refs": [],
            "cost": {"model_calls": 1, "tool_calls": 1},
            "summary": "Readonly child result.",
            "parent_worker_invocation_id": "worker-0001",
            "worker_kind": "subagent_readonly_child",
            "child_plan_refs": ["subagent-child-plan-0001"],
        },
        "worker_result",
    )
    jsonl.append(
        tmp_path / "subagent_child_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "subagent_child_plan_id": "subagent-child-plan-0001",
            "run_id": "run-1",
            "parent_task_id": "task-0001",
            "target_task_id": "task-0001",
            "parent_decision_id": "agent-loop-decision-0001",
            "parent_execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0001",
            "worker_result_id": "worker-result-0001",
            "runtime_profile_id": "runtime-profile-parent",
            "planner_id": "RuntimeSubagentPlanner",
            "decomposition_strategy": "readonly_fanout",
            "scheduling_strategy": "parallel_readonly_safe",
            "max_child_workers": 2,
            "coordination_policy": {"write_allowed": False},
            "status": "planned",
            "parallel_safety": "readonly",
            "child_tasks": [
                {
                    "child_task_id": "task-0001-child-01",
                    "task_id": "task-0001",
                    "title": "Inspect shard",
                    "objective": "Read shard.",
                    "acceptance": ["shard inspected"],
                    "read_scope": ["."],
                    "write_scope": [],
                    "allowed_tools": ["read_file"],
                    "depends_on": [],
                    "risk": "low",
                    "parallel_safety": "readonly",
                    "worker_role": "research_child",
                    "write_allowed": False,
                    "expected_output": ["validation-child-01"],
                    "verification_expectation": {"requires_verification": True},
                }
            ],
            "evidence_refs": ["agent_loop_execution_results.jsonl"],
            "created_at": "2026-05-29T10:00:01+08:00",
        },
        "subagent_child_plan",
    )

    graph = AgentRunGraphBuilder(validator).build(tmp_path, run_id="run-1")
    child_plan = next(
        item
        for item in graph["child_worker_plans"]
        if item["worker_invocation_id"] == "worker-0002"
    )

    assert child_plan["parent_worker_invocation_id"] == "worker-0001"
    assert child_plan["worker_kind"] == "subagent_readonly_child"
    assert child_plan["parallel_safety"] == "readonly"
    assert child_plan["child_plan_refs"] == ["subagent-child-plan-0001"]
    assert child_plan["subagent_child_plan_id"] == "subagent-child-plan-0001"
    assert child_plan["scheduling_strategy"] == "parallel_readonly_safe"
    assert child_plan["planned_child_count"] == 1


def test_worker_recorder_allocates_ids_from_existing_jsonl(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    recorder = WorkerExecutionRecorder(validator)
    (tmp_path / "workers.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    (tmp_path / "worker_results.jsonl").write_text("{}\n", encoding="utf-8")

    assert recorder.allocate_worker_ids(context, 2) == ["worker-0003", "worker-0004"]
    assert recorder.allocate_worker_result_ids(context, 2) == [
        "worker-result-0002",
        "worker-result-0003",
    ]

    slots = recorder.allocate_execution_slots(context, 2)
    assert [(slot.worker_id, slot.result_id) for slot in slots] == [
        ("worker-0003", "worker-result-0002"),
        ("worker-0004", "worker-result-0003"),
    ]


def test_delegation_quality_gate_blocks_high_risk_incomplete_brief() -> None:
    recorder = WorkerExecutionRecorder(SchemaValidator(Path.cwd() / "schemas"))

    gate = recorder.delegation_gate(
        {
            "task_id": "task-0001",
            "title": "Risky write without scope",
            "description": "Modify runtime behavior.",
            "risk_score": 0.9,
            "allowed_tools": ["write_file"],
        }
    )

    assert gate["status"] == "blocked"
    assert gate["risk"] == "high"
    assert "allowed_writes" in gate["brief_quality"]["missing_fields"]
    assert "expected_output" in gate["brief_quality"]["missing_fields"]


def test_delegation_quality_gate_allows_low_risk_warn_only_brief() -> None:
    recorder = WorkerExecutionRecorder(SchemaValidator(Path.cwd() / "schemas"))

    gate = recorder.delegation_gate(
        {
            "task_id": "task-0001",
            "title": "Inspect status",
            "description": "Read current status only.",
            "allowed_tools": ["read_file"],
        }
    )

    assert gate["status"] == "pass"
    assert gate["risk"] == "low"
    assert gate["brief_quality"]["status"] == "warn"


def test_delegation_quality_gate_allows_planned_scope_request() -> None:
    recorder = WorkerExecutionRecorder(SchemaValidator(Path.cwd() / "schemas"))

    gate = recorder.delegation_gate(
        {
            "task_id": "task-0001",
            "title": "Request scoped write",
            "description": "Prepare a runtime request for scoped writes.",
            "allowed_tools": ["write_file"],
            "expected_artifacts": ["src/"],
            "notes": "Scope quality: write_scope was broad, so require a runtime scope request.",
        }
    )

    assert gate["status"] == "pass"
    assert gate["risk"] == "scope_request"
    assert gate["brief_quality"]["status"] == "warn"


def test_delegation_quality_gate_allows_delegating_lead_with_empty_own_write_scope() -> None:
    """ADR-0023 real-stack finding: a model-driven lead that can spawn_subagent delegates its writes
    to child experts (each declares its own write_scope), so the lead's OWN write_scope is empty by
    design. The brief-quality gate must NOT block it solely for missing allowed_writes — the real
    write boundary is the gateway per-path scope + isolated-write merge gate, not this brief gate."""
    recorder = WorkerExecutionRecorder(SchemaValidator(Path.cwd() / "schemas"))

    gate = recorder.delegation_gate(
        {
            "task_id": "task-0001",
            "title": "并行实现两个独立模块",
            "description": "Delegate writing alpha.py and beta.py to two coder subagents in one batch.",
            "allowed_tools": ["read_file", "write_file", "run_command", "spawn_subagent"],
            "expected_artifacts": ["src/alpha.py", "src/beta.py"],
            "write_scope": [],
        }
    )

    assert gate["status"] == "pass"
    assert gate["risk"] == "write"
    assert gate["delegation_brief"]["delegates_writes"] is True
    assert "allowed_writes" not in gate["brief_quality"]["missing_fields"]


def test_delegation_quality_gate_still_blocks_direct_writer_without_scope() -> None:
    """Guardrail: a write-capable task that CANNOT delegate (no spawn_subagent) and declares no
    write_scope is still blocked — delegates_writes stays False, so allowed_writes is still required."""
    recorder = WorkerExecutionRecorder(SchemaValidator(Path.cwd() / "schemas"))

    gate = recorder.delegation_gate(
        {
            "task_id": "task-0001",
            "title": "Direct writer without scope",
            "description": "Write files directly.",
            "allowed_tools": ["write_file"],
            "expected_artifacts": ["src/out.py"],
            "write_scope": [],
        }
    )

    assert gate["status"] == "blocked"
    assert gate["risk"] == "write"
    assert gate["delegation_brief"]["delegates_writes"] is False
    assert "allowed_writes" in gate["brief_quality"]["missing_fields"]
