from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.deadline_budget import DeadlineBudget
from asteria_runtime.real_model_smoke import (
    P0_MATRIX_CASES,
    SmokeResult,
    apply_setup_files,
    build_parser,
    matrix_cases,
    run_from_args,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_p0_matrix_cases_cover_required_routes() -> None:
    cases = matrix_cases("p0")

    assert [case.name for case in cases] == [
        "file_output",
        "single_file_bugfix",
        "doc_update",
        "contract_mismatch_replan",
        "verification_failure_repair",
    ]
    assert {case.route for case in cases} >= {"artifact_creation", "repair", "replan"}
    assert {case.task_kind for case in cases} >= {
        "file_output",
        "bug_fix",
        "doc_update",
        "contract_mismatch",
        "verification_failure",
    }


def test_p0_matrix_case_filter_preserves_order() -> None:
    cases = matrix_cases("p0", ["doc_update", "file_output"])

    assert [case.name for case in cases] == ["doc_update", "file_output"]


def test_p0_matrix_writes_durable_summary(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_single(args, *, timeout_budget: DeadlineBudget, case=None):
        assert case is not None
        calls.append(case.name)
        workspace = Path(args.root)
        workspace.mkdir(parents=True, exist_ok=True)
        expected_file = workspace / args.expected_file
        expected_file.parent.mkdir(parents=True, exist_ok=True)
        expected_file.write_text(args.expected_text + "\n", encoding="utf-8")
        final_report = workspace / ".asteria" / "runs" / "run-matrix" / "final_report.md"
        final_report.parent.mkdir(parents=True, exist_ok=True)
        final_report.write_text("# Final\n", encoding="utf-8")
        result = SmokeResult(
            workspace=workspace,
            run_id="run-matrix",
            expected_file=expected_file,
            final_report=final_report,
            transcript=workspace / "real_model_smoke_transcript.json",
            diagnostics={"route": case.route},
        )
        result.ended_at = result.started_at
        return result, False

    monkeypatch.setattr("asteria_runtime.real_model_smoke.run_single_from_args", fake_run_single)
    summary_path = tmp_path / "matrix_summary_copy.json"
    output_dir = tmp_path / "matrix-output"
    args = build_parser().parse_args(
        [
            "--matrix",
            "p0",
            "--matrix-case",
            "file_output",
            "--matrix-case",
            "doc_update",
            "--matrix-output-dir",
            str(output_dir),
            "--summary-json",
            str(summary_path),
            "--allow-fake",
        ]
    )

    run_from_args(args)

    assert calls == ["file_output", "doc_update"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["matrix"] == "p0"
    assert summary["case_count"] == 2
    assert summary["passed"] == 2
    assert (output_dir / "matrix_summary.json").exists()
    assert [case["route"] for case in summary["cases"]] == [
        "artifact_creation",
        "artifact_creation",
    ]
    assert all(case["evidence_refs"] for case in summary["cases"])
    SchemaValidator(Path("schemas")).validate("real_provider_matrix_summary", summary)


def test_matrix_setup_files_stay_inside_workspace(tmp_path: Path) -> None:
    case = next(case for case in P0_MATRIX_CASES if case.name == "single_file_bugfix")

    apply_setup_files(tmp_path, case.setup_files)

    assert (tmp_path / "calc.py").read_text(encoding="utf-8").startswith("def add")
    assert (tmp_path / "test_calc.py").exists()
