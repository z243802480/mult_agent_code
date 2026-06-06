from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.runtime_validation_evidence import _record_swarm_matrix_probe_evidence
from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
from asteria_runtime.core.runtime_validation_evidence import (
    record_runtime_validation_matrix_evidence,
)
from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_runtime_validation_matrix_covers_fixed_real_task_cases(tmp_path: Path) -> None:
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
    _write_jsonl(
        run_dir / "capability_decisions.jsonl",
        [{"decision": {"decision": "allow", "reason": "covered by validation policy"}}],
    )
    _write_jsonl(
        run_dir / "mcp_invocations.jsonl",
        [{"capability_decision": {"reason": "mcp echo allowed"}}],
    )
    _write_jsonl(
        run_dir / "skill_invocations.jsonl",
        [{"capability_decision": {"reason": "document skill selected"}}],
    )
    _write_jsonl(
        run_dir / "user_progress.jsonl",
        [
            {
                "schema_version": "0.1.0",
                "event_id": "upe-1",
                "run_id": "run-1",
                "created_at": "2026-05-28T00:00:00Z",
                "channel": "tool",
                "event_type": "tool_output",
                "phase": "execute",
                "status": "completed",
                "title": "Skill adapter completed",
                "summary": "Skill adapter wrote an artifact.",
                "display_level": "main",
                "artifact_refs": [],
                "evidence_refs": [],
                "call_chain": [],
                "execution_chain": [],
                "file_changes": [],
                "data": {"capability_type": "skill"},
            }
        ],
    )
    validator = SchemaValidator(Path.cwd() / "schemas")
    (tmp_path / ".asteria" / "runs" / "run-1" / "runtime_validation_matrix_evidence.json").write_text(
        json.dumps({"schema_version": "0.1.0", "run_id": "run-1", "source": "unit-test"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / ".asteria" / "runs" / "run-gray").mkdir(parents=True)
    (tmp_path / ".asteria" / "runs" / "run-gray" / "production_gray_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "case_id": "dual_disjoint_files",
                "run_id": "run-gray",
                "ok": True,
                "execute_parallel_disjoint": True,
                "gray_rollback_drill_ok": True,
                "cli_parallel_writes_default": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / ".asteria" / "runs" / "run-swarm").mkdir(parents=True)
    _record_swarm_matrix_probe_evidence(
        run_dir=tmp_path / ".asteria" / "runs" / "run-swarm",
        run_id="run-swarm",
        validator=validator,
    )
    metrics = runtime_progress_metrics(tmp_path, validator)

    matrix = runtime_validation_matrix(tmp_path, metrics)

    by_id = {case["id"]: case for case in matrix["cases"]}
    for case_id in (
        "model_tool_surface",
        "skill_adapter",
        "mcp_adapter",
        "profile_research",
        "profile_brainstorm",
        "profile_multi_agent",
        "permission_reason",
        "runtime_progress",
        "swarm_disjoint_evidence",
        "dual_disjoint_files",
    ):
        assert by_id[case_id]["ok"] is True, case_id


def test_runtime_validation_matrix_evidence_probe_records_all_required_cases(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")

    evidence = record_runtime_validation_matrix_evidence(
        root=tmp_path,
        validator=validator,
        source="unit-test",
    )
    metrics = runtime_progress_metrics(tmp_path, validator)
    matrix = runtime_validation_matrix(tmp_path, metrics)

    assert evidence["run_id"].startswith("runtime-validation-matrix-")
    assert metrics["runtime_native_progress_coverage"]["matrix_evidence_runs"] == 1
    assert matrix["ready"] is True
    assert matrix["gap_summary"] == {
        "implementation_missing": 0,
        "evidence_missing": 0,
        "historical_evidence_noise": 0,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
