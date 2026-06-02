from __future__ import annotations

import json
import zipfile
from pathlib import Path

from asteria_runtime.commands.evidence_bundle_command import EvidenceBundleCommand


def test_evidence_bundle_redacts_and_summarizes_model_calls(tmp_path: Path) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "run_id": "run-0001",
                "status": "completed",
                "summary": "ok",
                "api_key": "secret-value",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "model_calls.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "model_call_id": "modelcall-0001",
                        "run_id": "run-0001",
                        "agent_id": "GoalSpecAgent",
                        "purpose": "goal_spec",
                        "model_provider": "zai",
                        "model_name": "glm-4.7",
                        "model_tier": "strong",
                        "status": "failure",
                        "created_at": "2026-05-20T00:00:00+08:00",
                        "summary": "stream deadline exceeded",
                        "duration_ms": 181000,
                        "streaming": {
                            "requested": True,
                            "mode": "streaming_failed",
                            "duration_ms": 181000,
                        },
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".asteria" / "model").mkdir()
    (tmp_path / ".asteria" / "model" / "capability_profile.json").write_text(
        json.dumps({"schema_version": "0.1.0", "profiles": [], "token": "hidden"}),
        encoding="utf-8",
    )
    validation_dir = tmp_path / ".asteria" / "validation_runs" / "validation-0001"
    validation_dir.mkdir(parents=True)
    root_summary = tmp_path / ".asteria" / "validation_runs" / "alpha2-summary-current.json"
    root_summary.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "validation_run_id": "validation-current",
                "status": "completed",
                "api_key": "secret-value",
            }
        ),
        encoding="utf-8",
    )
    (validation_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "validation_run_id": "validation-0001",
                "status": "blocked",
                "next_actions": ["repair route"],
                "api_key": "secret-value",
            }
        ),
        encoding="utf-8",
    )
    ops_dir = tmp_path / ".asteria" / "ops"
    ops_dir.mkdir()
    (ops_dir / "usage_signals.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "usage_signal_id": "usage-signal-0001",
                "signal_type": "artifact-outcome",
                "token": "hidden",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "usage_signal_analysis.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "status": "needs_attention",
                "priority_items": [],
                "roadmap_tasks": [],
                "candidate_decision_points": [],
                "secret": "hidden",
            }
        ),
        encoding="utf-8",
    )

    result = EvidenceBundleCommand(tmp_path).run()

    assert result.ok
    with zipfile.ZipFile(result.bundle_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "v0.2_rolling_validation_summary.json" in names
        assert ".asteria/runs/run-0001/run.json" in names
        assert ".asteria/runs/run-0001/model_calls.jsonl" in names
        assert ".asteria/validation_runs/alpha2-summary-current.json" in names
        assert ".asteria/validation_runs/validation-0001/summary.json" in names
        assert ".asteria/ops/usage_signals.jsonl" in names
        assert ".asteria/ops/usage_signal_analysis.json" in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["included_evidence"]["validation_runs"] is True
        assert manifest["included_evidence"]["ops_signals"] is True
        assert manifest["included_evidence"]["v0_2_rolling_validation"] is True
        assert (
            manifest["model_route_summary"]["zai/glm-4.7/goal_spec/strong"][
                "streaming_failed"
            ]
            == 1
        )
        run = json.loads(archive.read(".asteria/runs/run-0001/run.json").decode("utf-8"))
        assert run["api_key"] == "[REDACTED]"
        profile = json.loads(
            archive.read(".asteria/model/capability_profile.json").decode("utf-8")
        )
        assert profile["token"] == "[REDACTED]"
        validation = json.loads(
            archive.read(".asteria/validation_runs/validation-0001/summary.json").decode("utf-8")
        )
        assert validation["api_key"] == "[REDACTED]"
        root_validation = json.loads(
            archive.read(".asteria/validation_runs/alpha2-summary-current.json").decode("utf-8")
        )
        assert root_validation["api_key"] == "[REDACTED]"
        analysis = json.loads(
            archive.read(".asteria/ops/usage_signal_analysis.json").decode("utf-8")
        )
        assert analysis["secret"] == "[REDACTED]"
        usage_signal = archive.read(".asteria/ops/usage_signals.jsonl").decode("utf-8")
        assert "[REDACTED]" in usage_signal


def test_evidence_bundle_writes_v02_rolling_validation_summary(tmp_path: Path) -> None:
    for index in range(1, 4):
        run_id = f"run-000{index}"
        run_dir = tmp_path / ".asteria" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": run_id,
                    "status": "completed",
                    "current_phase": "ACCEPTED",
                    "summary": f"scoped real-provider task {index}",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "model_calls.jsonl").write_text(
            json.dumps(
                {
                    "model_provider": "zai",
                    "model_name": "glm-4.7",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                    "status": "success",
                    "deadline_ms": 120000,
                    "duration_ms": 2500 + index,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "context_budget_snapshots.jsonl").write_text(
            json.dumps(
                {
                    "snapshot_id": f"context-{index}",
                    "context_window_ratio": 0.1 * index,
                    "compact_boundary": {"status": "not_required"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "capability_decisions.jsonl").write_text(
            json.dumps(
                {
                    "capability_type": "tool",
                    "capability": "read_file",
                    "decision": {"decision": "allow", "reason": "scoped read"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "agent_loop_run_summary.json").write_text(
            json.dumps(
                {
                    "exit_reason": "completed",
                    "recommended_command": None,
                    "rounds_completed": 1,
                    "max_rounds": 2,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "workers.jsonl").write_text(
            json.dumps(
                {
                    "worker_invocation_id": f"worker-{index:04d}",
                    "status": "succeeded",
                    "worker_kind": "subagent",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "worker_results.jsonl").write_text(
            json.dumps(
                {
                    "worker_invocation_id": f"worker-{index:04d}",
                    "status": "succeeded",
                    "cost": {"model_calls": 1, "tool_calls": 1},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "agent_run_graph.json").write_text(
            json.dumps(
                {
                    "status": "succeeded",
                    "collaboration_summary": {
                        "total_workers": 1,
                        "successful_workers": 1,
                        "failed_workers": 0,
                    },
                }
            ),
            encoding="utf-8",
        )

    result = EvidenceBundleCommand(tmp_path).run()
    result_payload = result.to_dict()
    assert result_payload["v0_2_rolling_validation"]["status"] == "ready"
    assert result_payload["v0_2_rolling_validation"]["sample_count"] == 3
    assert "v0.2 rolling validation: ready (3 sample(s))" in result.to_text()

    with zipfile.ZipFile(result.bundle_path) as archive:
        names = set(archive.namelist())
        assert ".asteria/runs/run-0003/context_budget_snapshots.jsonl" in names
        assert ".asteria/runs/run-0003/capability_decisions.jsonl" in names
        assert ".asteria/runs/run-0003/agent_loop_run_summary.json" in names
        assert ".asteria/runs/run-0003/workers.jsonl" in names
        assert ".asteria/runs/run-0003/agent_run_graph.json" in names
        summary = json.loads(
            archive.read("v0.2_rolling_validation_summary.json").decode("utf-8")
        )
        assert summary["status"] == "ready"
        assert summary["sample_count"] == 3
        assert summary["coverage"] == {
            "route": True,
            "context": True,
            "capability": True,
            "loop": True,
            "worker": True,
        }
        assert len(summary["samples"]) == 3
        assert summary["samples"][0]["model_routes"][0]["route"] == (
            "zai/glm-4.7/task_execution/medium"
        )
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["v0_2_rolling_validation"]["status"] == "ready"
        assert manifest["v0_2_rolling_validation"]["sample_count"] == 3


def test_evidence_bundle_excludes_protected_route_files(tmp_path: Path) -> None:
    local_home = tmp_path / ".asteria"
    local_home.mkdir()
    (local_home / "model.routes.local.ps1").write_text(
        '$env:AGENT_MODEL_STRONG_API_KEY = "secret"',
        encoding="utf-8",
    )

    result = EvidenceBundleCommand(tmp_path).run()

    with zipfile.ZipFile(result.bundle_path) as archive:
        assert not any("model.routes.local" in name for name in archive.namelist())
