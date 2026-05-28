from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.recovery_pressure import recovery_pressure_report
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_recovery_pressure_report_covers_resume_replan_repair_memory_conflicts_and_permission(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _write_jsonl(
        run_dir / "user_progress.jsonl",
        [
            _progress_event(
                "upe-resume",
                "plan",
                "恢复会话",
                "Resume applied accepted permission decisions.",
            ),
            _progress_event(
                "upe-replan",
                "plan",
                "准备重规划",
                "Replan after contract mismatch.",
            ),
            _progress_event(
                "upe-repair",
                "execute",
                "开始修复",
                "Repair verification failure.",
            ),
            _progress_event(
                "upe-permission",
                "execute",
                "Permission decision recorded",
                "Permission approval was required.",
                event_type="permission_decision",
                channel="permission",
            ),
        ],
    )
    _write_jsonl(
        run_dir / "decisions.jsonl",
        [
            {
                "decision_id": "decision-1",
                "metadata": {"kind": "replan_decision"},
                "summary": "replan approved",
            },
            {
                "decision_id": "decision-2",
                "metadata": {"kind": "execution_policy_approval"},
                "summary": "permission approved",
            },
        ],
    )
    _write_jsonl(
        run_dir / "runtime_requests.jsonl",
        [{"runtime_request_id": "request-1", "summary": "permission approval required"}],
    )
    (run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"task_id": "task-repair", "title": "repair verification failure"},
                    {"task_id": "task-replan", "title": "replan blocked work"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "events.jsonl",
        [{"type": "context_compacted", "summary": "compact snapshot for continuation"}],
    )
    snapshots_dir = tmp_path / ".asteria" / "context" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    (snapshots_dir / "snapshot-1.json").write_text(
        json.dumps(
            {
                "snapshot_id": "snapshot-1",
                "compaction_purpose": "continuation_state_not_success_evidence",
                "next_actions": ["Continue the active task."],
            }
        ),
        encoding="utf-8",
    )
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "active_goal.json").write_text(
        json.dumps(
            {
                "update_reason": "recovery_from_corrupt_json",
                "current_blockers": ["Conflict: another unfinished run is active."],
            }
        ),
        encoding="utf-8",
    )

    report = recovery_pressure_report(tmp_path, SchemaValidator(Path.cwd() / "schemas"))

    assert report["ready"] is True
    assert report["coverage_ratio"] == 1.0
    assert report["missing"] == []
    assert all(chain["covered"] for chain in report["chains"].values())


def _progress_event(
    event_id: str,
    phase: str,
    title: str,
    summary: str,
    *,
    event_type: str = "start",
    channel: str = "progress",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "event_id": event_id,
        "run_id": "run-1",
        "created_at": "2026-05-28T00:00:00Z",
        "channel": channel,
        "event_type": event_type,
        "phase": phase,
        "status": "running",
        "title": title,
        "summary": summary,
        "display_level": "main",
        "artifact_refs": [],
        "evidence_refs": [],
        "call_chain": [],
        "execution_chain": [],
        "file_changes": [],
        "data": {},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
