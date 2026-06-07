from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_dynamic_live import (
    execute_merge_checkpoint_live,
    execute_verifier_fanout_dry,
    execute_verifier_fanout_live,
)
from asteria_runtime.core.orchestration_dynamic_runner import run_dynamic_orchestration
from asteria_runtime.core.orchestration_workflow_monitor import build_workflow_monitor_projection
from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy
from asteria_runtime.storage.schema_validator import SchemaValidator


def _manifest(*, include_fail_verifier: bool = False) -> dict:
    verdict = "fail" if include_fail_verifier else "pass"
    return {
        "schema_version": "0.1.0",
        "workflow_id": "s69-verifier-probe",
        "description": "S69 adversarial verifier before merge",
        "max_concurrent_steps": 2,
        "phases": [
            {
                "phase_id": "verify",
                "steps": [
                    {
                        "step_id": "adversarial-review",
                        "kind": "adversarial_review",
                        "tasks": [
                            {"task_id": "v1", "verdict": verdict},
                            {"task_id": "v2", "verdict": "pass"},
                        ],
                    }
                ],
            },
            {
                "phase_id": "merge",
                "steps": [{"step_id": "merge-checkpoint", "kind": "merge_checkpoint"}],
            },
        ],
    }


def test_verifier_dry_blocks_merge_on_fail() -> None:
    merge = execute_merge_checkpoint_live(
        run_dir=Path("unused"),
        prior_variables=[execute_verifier_fanout_dry(tasks=[{"verdict": "fail"}])["variables"]],
    )
    assert merge["ok"] is False
    assert merge["variables"]["verifier_gate_ok"] is False


def test_verifier_dry_allows_merge_on_pass() -> None:
    merge = execute_merge_checkpoint_live(
        run_dir=Path("unused"),
        prior_variables=[execute_verifier_fanout_dry(tasks=[{"verdict": "pass"}])["variables"]],
    )
    assert merge["ok"] is True
    assert merge["variables"]["verifier_gate_ok"] is True


def test_live_verifier_manifest(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    run_dir = tmp_path / ".asteria" / "runs" / "run-s69-live"
    result = run_dynamic_orchestration(
        manifest_path=manifest_path,
        run_dir=run_dir,
        policy=with_maintainer_probe_policy({}),
        dry_run=False,
        resume=False,
        root=tmp_path,
        validator=validator,
        run_id="run-s69-live",
    )
    assert result.ok is True
    projection = build_workflow_monitor_projection(run_dir, workflow_id="s69-verifier-probe")
    assert projection is not None
    assert projection["verifier_status"] == "passed"
    assert projection["merge_status"] == "passed"


def test_live_verifier_fail_stops_workflow(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(include_fail_verifier=True)), encoding="utf-8")
    run_dir = tmp_path / ".asteria" / "runs" / "run-s69-fail"
    result = run_dynamic_orchestration(
        manifest_path=manifest_path,
        run_dir=run_dir,
        policy=with_maintainer_probe_policy({}),
        dry_run=False,
        resume=False,
        root=tmp_path,
        validator=validator,
        run_id="run-s69-fail",
    )
    assert result.ok is False
    projection = build_workflow_monitor_projection(run_dir, workflow_id="s69-verifier-probe")
    assert projection is not None
    assert projection["verifier_status"] == "failed"


def test_execute_verifier_fanout_live_records_workers(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-verifier-live"
    result = execute_verifier_fanout_live(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-verifier-live",
        validator=validator,
        tasks=[{"task_id": "v1", "verdict": "pass"}],
        parent_task_id="probe:verify:adversarial",
    )
    assert result["ok"] is True
    assert result["verifier_status"] == "passed"
    assert (run_dir / "verifier_evidence" / "v1.txt").exists()
