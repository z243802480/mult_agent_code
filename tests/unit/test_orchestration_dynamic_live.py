from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_dynamic_live import (
    execute_disjoint_write_fanout_live,
    execute_readonly_fanout_live,
)
from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_readonly_fanout_live_records_workers(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-live-readonly"
    result = execute_readonly_fanout_live(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-live-readonly",
        validator=validator,
        tasks=[
            {"task_id": "r1", "parallel_safety": "readonly"},
            {"task_id": "r2", "parallel_safety": "readonly"},
        ],
        parent_task_id="probe:explore:readonly",
    )
    assert result["ok"] is True
    assert len(result["worker_ids"]) == 2
    assert (run_dir / "workers.jsonl").exists()
    assert (run_dir / "readonly_evidence" / "r1.txt").exists()


def test_disjoint_fanout_live_candidate_merge(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-live-disjoint"
    policy = with_maintainer_probe_policy({})
    result = execute_disjoint_write_fanout_live(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-live-disjoint",
        validator=validator,
        tasks=[
            {"task_id": "w1", "write_scope": [".asteria/orchestration_live/w1.txt"]},
            {"task_id": "w2", "write_scope": [".asteria/orchestration_live/w2.txt"]},
        ],
        parent_task_id="probe:write:disjoint",
        policy=policy,
    )
    assert result["ok"] is True
    assert result["merge_status"] == "passed"
    assert len(result["worker_ids"]) == 2
    assert (run_dir / "workers.jsonl").exists()
