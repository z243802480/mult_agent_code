from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.core.phase2_stability_audit import (
    evaluate_stability_gate,
    evaluate_stability_samples,
)
from asteria_runtime.real_model_smoke import P0_MATRIX_CASES, apply_setup_files

from tests.integration.test_phase3_rolling_gate import (
    _bugfix_execute_client,
    _doc_update_execute_client,
)
from tests.integration.test_run_command import FakePlanClient, FakeReviewClient

pytestmark = pytest.mark.workflow

GATE = json.loads(Path("benchmarks/phase2_stability_gate.json").read_text(encoding="utf-8"))
CASES_BY_NAME = {case.name: case for case in P0_MATRIX_CASES}


def test_phase2_stability_gate_fake_scoped_runs(tmp_path: Path) -> None:
    run_dirs: list[Path] = []
    for case_id in ("doc_update", "single_file_bugfix"):
        case = CASES_BY_NAME[case_id]
        workspace = tmp_path / case_id
        apply_setup_files(workspace, case.setup_files)
        InitCommand(workspace).run()
        execute_client = (
            _doc_update_execute_client(case)
            if case_id == "doc_update"
            else _bugfix_execute_client()
        )
        result = RunCommand(
            workspace,
            case.goal,
            permission_level="balanced",
            plan_model_client=FakePlanClient(),
            execute_model_client=execute_client,
            review_model_client=FakeReviewClient(),
            enable_research=False,
            max_iterations=3,
            max_tasks_per_iteration=1,
        ).run()
        assert result.status == "completed"
        run_dirs.append(workspace / ".asteria" / "runs" / result.run_id)

    audit = evaluate_stability_gate(GATE, run_dirs=run_dirs)

    assert audit["ok"] is True
    assert audit["sample_count"] >= 2
    assert audit["metrics"]["median_model_calls"] <= GATE["thresholds"]["median_model_calls_max"]
    assert audit["metrics"]["max_repair_attempts"] <= GATE["thresholds"]["max_repair_attempts_per_run"]


def test_evaluate_stability_samples_reports_slo_warnings_without_blocking() -> None:
    audit = evaluate_stability_samples(
        [
            {"permission_mode": "reviewed_auto", "model_calls": 8, "repair_attempts": 0},
            {"permission_mode": "reviewed_auto", "model_calls": 6, "repair_attempts": 2},
        ],
        median_model_calls_max=5,
        max_repair_attempts_per_run=1,
    )

    assert audit["ok"] is True
    assert audit["status"] == "pass_with_warnings"
    assert audit["violations"] == []
    assert len(audit["slo_warnings"]) == 2
