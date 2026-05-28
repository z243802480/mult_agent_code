import json
from pathlib import Path

from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_runtime_progress_metrics_counts_profile_permission_and_progress(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "profile_counts": {
                    "research": 1,
                    "brainstorm": 1,
                    "multi_agent": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "capability_decisions.jsonl").write_text(
        json.dumps(
            {
                "decision": {
                    "decision": "ask",
                    "reason": "capability is available but requires a decision",
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "mcp_invocations.jsonl").write_text(
        json.dumps(
            {
                "mcp_invocation_id": "mcp-0001",
                "capability_decision": {"reason": "allowed by policy"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "skill_invocations.jsonl").write_text(
        json.dumps(
            {
                "skill_invocation_id": "skill-0001",
                "capability_decision": {"reason": "matching artifact skill"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "user_progress.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "event_id": "upe-1",
                "run_id": "run-1",
                "created_at": "2026-05-28T00:00:00Z",
                "channel": "permission",
                "event_type": "permission_decision",
                "phase": "execute",
                "status": "running",
                "title": "Capability decision recorded",
                "summary": "recorded",
                "display_level": "main",
                "artifact_refs": [],
                "evidence_refs": [],
                "call_chain": [],
                "execution_chain": [],
                "file_changes": [],
                "data": {"capability_type": "skill"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = runtime_progress_metrics(tmp_path, SchemaValidator(Path.cwd() / "schemas"))

    assert metrics["profile_coverage"]["coverage_ratio"] == 1.0
    assert metrics["permission_reason_coverage"]["coverage_ratio"] == 1.0
    assert metrics["runtime_native_progress_coverage"]["coverage_ratio"] == 1.0
    assert metrics["adapter_invocation_coverage"]["mcp_invocation_count"] == 1
    assert metrics["adapter_invocation_coverage"]["skill_invocation_count"] == 1
    assert metrics["adapter_invocation_coverage"]["mcp_with_reason"] == 1
    assert metrics["adapter_invocation_coverage"]["skill_with_reason"] == 1
    assert metrics["adapter_invocation_coverage"]["capability_progress_event_count"] == 1
