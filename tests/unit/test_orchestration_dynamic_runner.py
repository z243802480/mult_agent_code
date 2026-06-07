from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.orchestration_dynamic_runner import (
    load_orchestration_manifest,
    resolve_max_concurrent_steps,
    run_dynamic_orchestration,
)


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "workflow_id": "test-l3",
                "description": "Unit test manifest",
                "max_concurrent_steps": 2,
                "phases": [
                    {
                        "phase_id": "p1",
                        "steps": [
                            {
                                "step_id": "fanout-1",
                                "kind": "readonly_fanout",
                                "tasks": [
                                    {"task_id": "t1", "parallel_safety": "readonly"},
                                    {"task_id": "t2", "parallel_safety": "readonly"},
                                ],
                            },
                            {"step_id": "checkpoint-1", "kind": "merge_checkpoint"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_manifest_and_concurrency_cap(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    manifest = load_orchestration_manifest(manifest_path)
    assert manifest.workflow_id == "test-l3"
    assert manifest.total_steps() == 2
    capped = resolve_max_concurrent_steps(
        manifest,
        {"agent_loop": {"max_parallel_workers_per_run": 1}},
    )
    assert capped == 1


def test_dry_run_and_resume(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    run_dir = tmp_path / "run"

    first = run_dynamic_orchestration(
        manifest_path=manifest_path,
        run_dir=run_dir,
        policy={"agent_loop": {"max_parallel_workers_per_run": 16}},
        dry_run=True,
        resume=False,
    )
    assert first.ok is True
    assert first.completed_steps == 2
    assert first.state_path.exists()

    second = run_dynamic_orchestration(
        manifest_path=manifest_path,
        run_dir=run_dir,
        policy={"agent_loop": {"max_parallel_workers_per_run": 16}},
        dry_run=True,
        resume=True,
    )
    assert second.ok is True
    assert second.completed_steps == 2
    assert second.resume_checkpoint == "checkpoint-1"

    state_lines = second.state_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(state_lines) == 2

    footprint = first.manifest_footprint
    assert footprint["step_count"] == 2
    assert footprint["context_budget_bytes"] == 512


def test_live_orchestration_manifest(tmp_path: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "workflow_id": "live-test",
                "description": "live",
                "max_concurrent_steps": 2,
                "phases": [
                    {
                        "phase_id": "p1",
                        "steps": [
                            {
                                "step_id": "read-live",
                                "kind": "readonly_fanout",
                                "tasks": [{"task_id": "lr1", "parallel_safety": "readonly"}],
                            },
                            {"step_id": "merge-1", "kind": "merge_checkpoint"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / ".asteria" / "runs" / "run-l3-live"
    result = run_dynamic_orchestration(
        manifest_path=manifest_path,
        run_dir=run_dir,
        policy=with_maintainer_probe_policy({}),
        dry_run=False,
        resume=False,
        root=tmp_path,
        validator=validator,
        run_id="run-l3-live",
    )
    assert result.ok is True
    assert result.dry_run is False
    assert (run_dir / "workers.jsonl").exists()
    assert (run_dir / "orchestration_runner_state.jsonl").exists()
