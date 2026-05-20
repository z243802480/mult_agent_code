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

    result = EvidenceBundleCommand(tmp_path).run()

    assert result.ok
    with zipfile.ZipFile(result.bundle_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert ".asteria/runs/run-0001/run.json" in names
        assert ".asteria/runs/run-0001/model_calls.jsonl" in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
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
