from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.run_health_audit import (
    evaluate_run_health,
    evaluate_run_health_from_manifest,
    sample_run_health,
)


def test_sample_run_health_reads_progress_and_replan_counts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-0001", "status": "completed", "current_phase": "DONE"}),
        encoding="utf-8",
    )
    (run_dir / "cost_report.json").write_text(
        json.dumps({"repair_attempts": 1, "model_calls": 3}),
        encoding="utf-8",
    )
    (run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"task_id": "task-0001", "status": "done"},
                    {
                        "task_id": "task-0002",
                        "status": "done",
                        "replan": {"source_task_id": "task-0001"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "user_progress.jsonl").write_text('{"event_type":"start"}\n', encoding="utf-8")

    sample = sample_run_health(run_dir)

    assert sample["run_status"] == "completed"
    assert sample["replan_task_count"] == 1
    assert sample["user_progress_events"] == 1


def test_evaluate_run_health_fails_on_blocked_status_and_large_progress() -> None:
    audit = evaluate_run_health(
        {
            "run_status": "blocked",
            "user_progress_bytes": 6_000_000,
            "user_progress_events": 3000,
            "replan_task_count": 20,
            "repair_attempts": 10,
        }
    )

    assert audit["ok"] is False
    assert audit["status"] == "fail"
    assert len(audit["violations"]) == 3
    assert len(audit["slo_warnings"]) == 2


def test_evaluate_run_health_passes_healthy_sample() -> None:
    audit = evaluate_run_health(
        {
            "run_status": "completed",
            "user_progress_bytes": 120_000,
            "user_progress_events": 80,
            "replan_task_count": 1,
            "repair_attempts": 1,
        }
    )

    assert audit["ok"] is True
    assert audit["status"] == "pass"
    assert audit["slo_warnings"] == []


def test_evaluate_run_health_keeps_repair_and_replan_counts_as_slo_warnings() -> None:
    audit = evaluate_run_health(
        {
            "run_status": "completed",
            "user_progress_bytes": 120_000,
            "user_progress_events": 80,
            "replan_task_count": 9,
            "repair_attempts": 7,
        }
    )

    assert audit["ok"] is True
    assert audit["status"] == "pass_with_warnings"
    assert audit["violations"] == []
    assert len(audit["slo_warnings"]) == 2


def test_evaluate_run_health_from_manifest_reads_gate_thresholds(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-0001", "status": "completed"}),
        encoding="utf-8",
    )
    (run_dir / "task_plan.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    manifest = json.loads(Path("benchmarks/phase4_run_health_gate.json").read_text(encoding="utf-8"))
    audit = evaluate_run_health_from_manifest(manifest, run_dir)

    assert audit["thresholds"]["max_replan_tasks"] == 8
    assert audit["ok"] is True
