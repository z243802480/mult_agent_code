from pathlib import Path

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
