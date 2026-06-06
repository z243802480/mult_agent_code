from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.swarm_flag_rollout import maintainer_probe_environment
from asteria_runtime.core.swarm_gray_decision import run_gray_rollback_drill
from asteria_runtime.core.swarm_production_gray import (
    PRODUCTION_GRAY_DECISION_KIND,
    evaluate_production_gray_readiness,
    find_production_gray_evidence,
    load_dual_worker_case,
    run_dual_disjoint_execute_scenario,
    run_production_gray_band,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_dual_worker_case_contract() -> None:
    case = load_dual_worker_case()
    assert case["case_id"] == "dual_disjoint_files"
    assert case["harness_requirements"]["parallel_writes"] is True
    assert case["harness_requirements"]["min_write_scopes"] == 2
    assert "workers.jsonl" in case["expected_evidence"]


def test_production_gray_blocked_without_gray_drill() -> None:
    policy = {"feature_flags": {"real_disjoint_write_workers": {"enabled": False}}}
    result = evaluate_production_gray_readiness(
        policy,
        gray_rollback_drill_ok=False,
        scenario_gate_ok=True,
        dual_worker_audit_ok=True,
        cli_parallel_writes_default=False,
    )
    assert result.ready is False
    assert "gray_rollback_drill_missing" in result.blockers


def test_production_gray_blocked_without_dual_worker_audit() -> None:
    policy = {"feature_flags": {"real_disjoint_write_workers": {"enabled": False}}}
    result = evaluate_production_gray_readiness(
        policy,
        gray_rollback_drill_ok=True,
        scenario_gate_ok=True,
        dual_worker_audit_ok=False,
        environment=maintainer_probe_environment(real_model_available=True),
        cli_parallel_writes_default=False,
    )
    assert result.ready is False
    assert "dual_worker_audit_missing" in result.blockers


def test_production_gray_ready_when_prerequisites_met() -> None:
    policy = {"feature_flags": {"real_disjoint_write_workers": {"enabled": False}}}
    result = evaluate_production_gray_readiness(
        policy,
        gray_rollback_drill_ok=True,
        scenario_gate_ok=True,
        dual_worker_audit_ok=True,
        environment=maintainer_probe_environment(real_model_available=True),
        cli_parallel_writes_default=False,
    )
    assert result.ready is True
    assert result.dual_worker_case_id == "dual_disjoint_files"


def test_production_gray_blocks_cli_default_flip() -> None:
    policy = {"feature_flags": {"real_disjoint_write_workers": {"enabled": True}}}
    result = evaluate_production_gray_readiness(
        policy,
        gray_rollback_drill_ok=True,
        scenario_gate_ok=True,
        dual_worker_audit_ok=True,
        environment=maintainer_probe_environment(),
        cli_parallel_writes_default=True,
    )
    assert result.ready is False
    assert "cli_parallel_writes_default_on" in result.blockers


def test_dual_disjoint_execute_scenario_passes_audit(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    result = run_dual_disjoint_execute_scenario(tmp_path, validator)
    assert result.ok is True
    assert "execute_parallel_disjoint" in result.detected_paths
    assert (tmp_path / "out" / "alpha.txt").exists()
    assert (tmp_path / "out" / "beta.txt").exists()


def test_production_gray_band_records_evidence(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    band = run_production_gray_band(tmp_path, validator)
    assert band.ok is True
    assert band.gray_drill_ok is True
    assert band.readiness.ready is True
    assert band.decision_point["metadata"]["kind"] == PRODUCTION_GRAY_DECISION_KIND
    assert band.evidence_path.exists()
    payload = json.loads(band.evidence_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["cli_parallel_writes_default"] is False
    assert find_production_gray_evidence(tmp_path) is not None


def test_gray_drill_satisfies_production_prerequisite(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-s34"
    drill = run_gray_rollback_drill(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-s34",
        validator=validator,
    )
    assert drill.ok is True
    policy = {"feature_flags": {"real_disjoint_write_workers": {"enabled": False}}}
    result = evaluate_production_gray_readiness(
        policy,
        gray_rollback_drill_ok=drill.ok,
        scenario_gate_ok=True,
        dual_worker_audit_ok=True,
        environment=maintainer_probe_environment(),
        cli_parallel_writes_default=False,
    )
    assert result.ready is True
