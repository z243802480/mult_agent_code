from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
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
    metrics = runtime_progress_metrics(tmp_path, validator)

    matrix = runtime_validation_matrix(tmp_path, metrics)

    assert matrix["ready"] is True
    assert matrix["passed"] == matrix["case_count"]
    assert {case["id"] for case in matrix["cases"]} >= {
        "model_tool_surface",
        "skill_adapter",
        "mcp_adapter",
        "profile_research",
        "profile_brainstorm",
        "profile_multi_agent",
        "permission_reason",
        "runtime_progress",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
