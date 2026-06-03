from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.deadline_budget import DeadlineBudget
from asteria_runtime.real_model_smoke import (
    P0_MATRIX_CASES,
    SmokeResult,
    apply_setup_files,
    build_parser,
    matrix_case_summary,
    matrix_cases,
    matrix_preset_case_names,
    run_from_args,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_p0_matrix_cases_cover_required_routes() -> None:
    cases = matrix_cases("p0")

    assert [case.name for case in cases] == [
        "file_output",
        "single_file_bugfix",
        "doc_update",
        "context_maintenance",
        "contract_mismatch_replan",
        "verification_failure_repair",
    ]
    assert {case.route for case in cases} >= {
        "artifact_creation",
        "context_slimming",
        "repair",
        "replan",
    }
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


def test_rolling_fastpath_matrix_preset_selects_fixed_subset() -> None:
    assert matrix_preset_case_names("rolling-fastpath-v1") == [
        "doc_update",
        "single_file_bugfix",
        "context_maintenance",
    ]


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
        (final_report.parent / "agent_loop_run_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": "run-matrix",
                    "task_id": "task-1",
                    "created_at": "2026-06-03T10:00:00+08:00",
                    "status": "completed",
                    "exit_reason": "completed",
                    "rounds_completed": 1,
                    "max_rounds": 2,
                    "summary": "Matrix case completed.",
                    "recommended_command": None,
                    "latest_decision_id": "agent-loop-decision-0001",
                    "latest_execution_id": "agent-loop-execution-0001",
                    "latest_observation_id": "agent-loop-observation-0001",
                    "latest_action": "tool",
                    "budget": {
                        "status": "within_budget",
                        "highest_label": "model_calls",
                        "highest_ratio": 0.1,
                        "model_calls": 1,
                        "tool_calls": 1,
                        "tool_budget_units": 1,
                        "repair_attempts": 0,
                        "warnings": [],
                    },
                    "context_pressure": {
                        "status": "within_budget",
                        "context_window_ratio": 0.05,
                        "context_window_tokens": 1000000,
                        "latest_context_estimated_tokens": 50000,
                        "max_context_estimated_tokens": 50000,
                        "context_compactions": 0,
                        "duplicate_content_hash_count": 0,
                    },
                    "recovery_chain": {
                        "required": False,
                        "satisfied": True,
                        "latest_action": "tool",
                        "observation_status": "succeeded",
                        "observation_next_recommended_action": None,
                        "allowed_actions": ["ask", "repair", "replan", "stop"],
                        "reason": "No recovery required.",
                    },
                    "evidence_refs": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (final_report.parent / "model_calls.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "schema_version": "0.1.0",
                            "model_call_id": "modelcall-0001",
                            "run_id": "run-matrix",
                            "agent_id": "CoderAgent",
                            "purpose": "task_execution",
                            "model_provider": "fake",
                            "model_name": "fake",
                            "model_tier": "medium",
                            "context_mode": "slim",
                            "fast_path_task_kind": "simple_file",
                            "context_estimate": {"estimated_tokens": 1000},
                            "input_tokens": 10,
                            "output_tokens": 20,
                            "status": "success",
                            "created_at": "2026-06-03T10:00:00+08:00",
                            "summary": "model call succeeded",
                        }
                    ),
                    json.dumps(
                        {
                            "schema_version": "0.1.0",
                            "model_call_id": "modelcall-0002",
                            "run_id": "run-matrix",
                            "agent_id": "ReviewAgent",
                            "purpose": "run_review",
                            "model_provider": "fake",
                            "model_name": "fake",
                            "model_tier": "medium",
                            "context_mode": "slim",
                            "fast_path_task_kind": "simple_file",
                            "context_estimate": {"estimated_tokens": 2000},
                            "input_tokens": 10,
                            "output_tokens": 20,
                            "status": "success",
                            "created_at": "2026-06-03T10:00:01+08:00",
                            "summary": "model call succeeded",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
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
    assert summary["matrix_preset"] is None
    assert summary["provider_mode"] == "fake"
    assert [case["route"] for case in summary["cases"]] == [
        "artifact_creation",
        "artifact_creation",
    ]
    assert all(case["evidence_refs"] for case in summary["cases"])
    assert all(case["agent_loop"]["status"] == "recorded" for case in summary["cases"])
    assert all(case["agent_loop"]["recovery_satisfied"] is True for case in summary["cases"])
    assert all(case["context_strategy"]["status"] == "recorded" for case in summary["cases"])
    assert all(case["context_strategy"]["slim_model_calls"] == 2 for case in summary["cases"])
    assert all(case["context_strategy"]["strong_model_calls"] == 0 for case in summary["cases"])
    assert all(case["context_strategy"]["run_review_model_calls"] == 1 for case in summary["cases"])
    assert all(case["context_strategy"]["task_execution_model_calls"] == 1 for case in summary["cases"])
    SchemaValidator(Path("schemas")).validate("real_provider_matrix_summary", summary)


def test_p0_matrix_preset_writes_fixed_rolling_subset(tmp_path: Path, monkeypatch) -> None:
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
    output_dir = tmp_path / "matrix-output"
    summary_path = tmp_path / "matrix-summary.json"
    args = build_parser().parse_args(
        [
            "--matrix-preset",
            "rolling-fastpath-v1",
            "--matrix-output-dir",
            str(output_dir),
            "--summary-json",
            str(summary_path),
            "--allow-fake",
        ]
    )

    run_from_args(args)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert calls == ["doc_update", "single_file_bugfix", "context_maintenance"]
    assert summary["matrix"] == "p0"
    assert summary["matrix_preset"] == "rolling-fastpath-v1"
    assert summary["provider_mode"] == "fake"
    assert [case["name"] for case in summary["cases"]] == calls
    SchemaValidator(Path("schemas")).validate("real_provider_matrix_summary", summary)


def test_matrix_case_summary_extracts_context_strategy_from_failed_workspace(
    tmp_path: Path,
) -> None:
    case = P0_MATRIX_CASES[0]
    workspace = tmp_path / "failed-workspace"
    run_dir = workspace / ".asteria" / "runs" / "run-failed"
    run_dir.mkdir(parents=True)
    (workspace / ".asteria" / "current_session.json").write_text(
        json.dumps({"session_id": "run-failed"}),
        encoding="utf-8",
    )
    (run_dir / "model_calls.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "model_call_id": "modelcall-0001",
                "run_id": "run-failed",
                "agent_id": "CoderAgent",
                "purpose": "task_execution",
                "model_provider": "fake",
                "model_name": "fake",
                "model_tier": "medium",
                "context_mode": "slim",
                "fast_path_task_kind": "simple_file",
                "context_estimate": {"total_tokens": 1200},
                "input_tokens": 10,
                "output_tokens": 20,
                "status": "success",
                "created_at": "2026-06-03T10:00:00+08:00",
                "summary": "model call succeeded",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = matrix_case_summary(
        case,
        workspace=workspace,
        summary_json=tmp_path / "case_summary.json",
        failure=RuntimeError("expected failure"),
    )

    assert summary["run_id"] is None
    assert summary["context_strategy"]["status"] == "recorded"
    assert summary["context_strategy"]["slim_model_calls"] == 1
    assert summary["context_strategy"]["context_modes"] == {"slim": 1}
    assert summary["context_strategy"]["model_tiers"] == {"medium": 1}
    assert summary["context_strategy"]["purposes"] == {"task_execution": 1}
    assert summary["context_strategy"]["strong_model_calls"] == 0
    assert summary["context_strategy"]["task_execution_model_calls"] == 1
    assert summary["context_strategy"]["task_repair_model_calls"] == 0
    assert summary["context_strategy"]["average_context_estimated_tokens"] == 1200


def test_matrix_setup_files_stay_inside_workspace(tmp_path: Path) -> None:
    case = next(case for case in P0_MATRIX_CASES if case.name == "single_file_bugfix")

    apply_setup_files(tmp_path, case.setup_files)

    assert (tmp_path / "calc.py").read_text(encoding="utf-8").startswith("def add")
    assert (tmp_path / "test_calc.py").exists()


def test_context_maintenance_matrix_case_seeds_local_context(tmp_path: Path) -> None:
    case = next(case for case in P0_MATRIX_CASES if case.name == "context_maintenance")

    apply_setup_files(tmp_path, case.setup_files)

    assert case.route == "context_slimming"
    assert case.expected_file == "docs/context_maintenance_summary.md"
    capability_notes = (tmp_path / "docs" / "capability_notes.md").read_text(encoding="utf-8")
    assert "real provider subsets" in capability_notes.lower()
