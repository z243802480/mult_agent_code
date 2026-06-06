from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.swarm_gray_decision import (
    GRAY_DECISION_KIND,
    build_gray_enable_decision_point,
    persist_gray_decision_point,
    run_gray_rollback_drill,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_build_gray_enable_decision_point_metadata() -> None:
    decision = build_gray_enable_decision_point(run_id="run-gray-001")
    assert decision["status"] == "pending"
    assert decision["metadata"]["kind"] == GRAY_DECISION_KIND
    assert decision["metadata"]["cli_parallel_writes_unchanged"] is True
    assert any(option["option_id"] == "rollback_now" for option in decision["options"])


def test_persist_gray_decision_point_writes_jsonl(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / "run-gray"
    decision = persist_gray_decision_point(
        run_dir=run_dir,
        validator=validator,
        run_id="run-gray-002",
    )
    path = run_dir / "decisions.jsonl"
    assert path.exists()
    assert decision["decision_id"] in path.read_text(encoding="utf-8")


def test_gray_rollback_drill_end_to_end(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-gray-drill"
    result = run_gray_rollback_drill(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-gray-drill",
        validator=validator,
        policy={},
    )
    assert result.enable_plan.safe is True
    assert result.rollback_plan.to_enabled is False
    assert (run_dir / "swarm_gray_rollout_records.jsonl").exists()
    records = (run_dir / "swarm_gray_rollout_records.jsonl").read_text(encoding="utf-8")
    assert "rollback_ok" in records
    assert result.probe_ok is True
    assert result.ok is True
