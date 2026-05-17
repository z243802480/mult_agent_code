from pathlib import Path

from asteria_runtime.core.runtime_evidence import RuntimeEvidenceReader
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_runtime_evidence_reader_groups_task_worker_merge_and_request_evidence(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    jsonl = JsonlStore(validator)
    jsonl.append(
        tmp_path / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "evidence-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "status": "blocked",
            "summary": "merge gate blocked",
            "failure_type": "merge_gate",
            "task": {},
            "action": {},
            "candidate": {},
            "contract_check": {"merge_gate": {"ok": False, "violations": ["outside scope"]}},
            "tool_results": [],
            "verification_results": [],
            "created_at": "2026-05-14T10:00:00+08:00",
        },
        "task_execution_evidence",
    )
    jsonl.append(
        tmp_path / "worker_results.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_result_id": "worker-result-0001",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "status": "failed",
            "artifact_refs": [],
            "validation_refs": [],
            "failure_evidence_refs": ["failure-0001"],
            "cost": {"model_calls": 1, "tool_calls": 1},
            "summary": "blocked",
        },
        "worker_result",
    )
    jsonl.append(
        tmp_path / "runtime_requests.jsonl",
        {
            "schema_version": "0.1.0",
            "runtime_request_id": "runtime-request-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "request_type": "scope_expansion",
            "risk": "medium",
            "reason": "Need another file",
            "details": {"write_scope": ["src/extra.py"]},
            "status": "decision_created",
            "decision_id": "decision-0001",
            "created_at": "2026-05-14T10:00:01+08:00",
        },
        "runtime_request",
    )

    evidence = RuntimeEvidenceReader(validator).task_evidence(tmp_path, "task-0001")

    assert evidence["summary"]["blocked_execution_count"] == 1
    assert evidence["summary"]["failed_worker_result_count"] == 1
    assert evidence["summary"]["merge_gate_block_count"] == 1
    assert evidence["summary"]["pending_runtime_request_count"] == 1
    assert evidence["merge_gate_evidence"][0]["merge_gate"]["ok"] is False
