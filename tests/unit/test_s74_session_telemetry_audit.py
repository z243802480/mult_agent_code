from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand
from asteria_runtime.core.s74_session_telemetry_audit import (
    audit_run_session_consistency,
    audit_session_telemetry,
    apply_session_audit_to_unified,
)


def _write_manifest(root: Path) -> Path:
    manifest = root / "benchmarks" / "studio_user_tasks.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "minimum_ready_score": 0.8,
                "required_user_progress_kinds": [
                    "plan",
                    "tool_use",
                    "tool_result",
                    "file_change",
                    "verification",
                    "final",
                ],
                "tasks": [{"id": "doc", "goal": "update doc", "required_events": ["user_message"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def _semantic_progress() -> list[dict]:
    return [
        {"transcript_kind": "plan", "display_level": "main", "summary": "Plan"},
        {"transcript_kind": "tool_use", "display_level": "main", "summary": "Edit"},
        {"transcript_kind": "tool_result", "display_level": "main", "summary": "Done"},
        {"transcript_kind": "verification", "display_level": "main", "summary": "Verified"},
        {"transcript_kind": "file_change", "display_level": "main", "summary": "Changed"},
        {"transcript_kind": "final", "display_level": "main", "summary": "Complete"},
    ]


def test_audit_session_telemetry_records_slo_warnings_without_blocking() -> None:
    audit = audit_session_telemetry(
        {
            "goal_completed": True,
            "model_calls": 12,
            "repair_count": 0,
            "elapsed_total": 50.0,
        },
        slot_id="session_doc_update",
    )

    assert audit["mode"] == "audit_only"
    assert audit["matrix_blocking"] is False
    assert audit["slo_status"] == "pass_with_warnings"
    assert any("model_calls" in item for item in audit["slo_warnings"])


def test_audit_run_session_consistency_uses_workspace_runs_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    manifest = _write_manifest(repo)
    run_id = "run-matrix-001"
    run_dir = workspace / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "user_progress.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in _semantic_progress())
        + "\n",
        encoding="utf-8",
    )

    result = audit_run_session_consistency(
        repo_root=repo,
        workspace=workspace,
        run_id=run_id,
        manifest=manifest,
    )

    assert result["user_progress_consistent"] is True
    assert result["studio_runtime_consistent"] is True
    assert result["score"] >= 0.8


def test_studio_benchmark_runs_root_scopes_isolated_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    manifest = _write_manifest(repo)
    good_run = "good-run"
    bad_run = "bad-run"
    for run_id, events in (
        (good_run, _semantic_progress()),
        (
            bad_run,
            [
                {
                    "channel": "model",
                    "event_type": "delta",
                    "display_level": "main",
                    "transcript_kind": "assistant_message",
                    "content_delta": "<think>leak</think>",
                }
            ],
        ),
    ):
        run_dir = workspace / ".asteria" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "user_progress.jsonl").write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
            encoding="utf-8",
        )

    scoped = StudioBenchmarkCommand(
        repo,
        manifest=manifest,
        run_id=good_run,
        runs_root=workspace / ".asteria" / "runs",
    ).run()

    assert scoped.ok is True
    assert scoped.user_progress_events == 6


def test_apply_session_audit_merges_unified_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    manifest = _write_manifest(repo)
    run_id = "run-apply"
    run_dir = workspace / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "user_progress.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in _semantic_progress())
        + "\n",
        encoding="utf-8",
    )
    unified = {
        "goal_completed": True,
        "model_calls": 3,
        "repair_count": 0,
        "elapsed_total": 45.0,
    }

    apply_session_audit_to_unified(
        unified,
        repo_root=repo,
        workspace=workspace,
        run_id=run_id,
        manifest=manifest,
        slot_id="session_small_cli",
    )

    assert unified["user_progress_consistent"] is True
    assert unified["studio_runtime_consistent"] is True
    assert unified["session_audit"]["telemetry"]["mode"] == "audit_only"
