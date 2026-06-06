from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.phase2_stability_audit import (
    evaluate_stability_samples,
    sample_matrix_case,
    sample_run_stability,
)


def test_sample_run_stability_reads_cost_report_and_permission_mode(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-0001", "status": "completed"}),
        encoding="utf-8",
    )
    (run_dir / "workspace_envelope.json").write_text(
        json.dumps({"permission_mode": "reviewed_auto"}),
        encoding="utf-8",
    )
    (run_dir / "cost_report.json").write_text(
        json.dumps({"model_calls": 3, "repair_attempts": 0}),
        encoding="utf-8",
    )

    sample = sample_run_stability(run_dir)

    assert sample["permission_mode"] == "reviewed_auto"
    assert sample["model_calls"] == 3
    assert sample["repair_attempts"] == 0


def test_load_matrix_summary_samples_maps_diagnostics() -> None:
    summary = {
        "cases": [
            {
                "name": "doc_update",
                "diagnostics": {"model_calls": 2, "repair_attempts": 0, "run_status": "completed"},
            },
            {
                "name": "single_file_bugfix",
                "diagnostics": {"model_calls": 2, "repair_attempts": 0, "run_status": "completed"},
            },
        ]
    }
    samples = [sample_matrix_case(case) for case in summary["cases"]]
    samples = [sample for sample in samples if sample is not None]

    assert len(samples) == 2
    assert all(sample["permission_mode"] == "reviewed_auto" for sample in samples)
    assert all(sample["model_calls"] <= 5 for sample in samples)


def test_evaluate_stability_samples_passes_within_thresholds() -> None:
    audit = evaluate_stability_samples(
        [
            {"permission_mode": "reviewed_auto", "model_calls": 2, "repair_attempts": 0},
            {"permission_mode": "reviewed_auto", "model_calls": 4, "repair_attempts": 1},
        ]
    )

    assert audit["ok"] is True
    assert audit["metrics"]["median_model_calls"] == 3.0
