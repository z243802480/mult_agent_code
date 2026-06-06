from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.core.swarm_production_gray import (
    load_dual_worker_case,
    run_production_gray_band,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


GATE = json.loads(Path("benchmarks/phase5f_production_gray_gate.json").read_text(encoding="utf-8"))


def test_phase5f_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "5"
    assert GATE["wave"] == "6"
    assert Path(GATE["plan"]).exists()
    assert Path(GATE["dual_worker_case"]).exists()
    for rel in GATE["depends_on_gates"]:
        assert Path(rel).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    production = GATE["production_gray"]
    assert production["cli_parallel_writes_default"] is False
    assert production["requires_gray_rollback_drill"] is True
    assert production["beta_default_session_agent"] is True


def test_dual_worker_case_matches_gate_ref() -> None:
    case = load_dual_worker_case()
    assert GATE["dual_worker_case"].endswith("phase5_dual_worker_case.json")
    assert case["case_id"] == "dual_disjoint_files"
    signoff = GATE["real_provider_signoff"]
    assert signoff["optional"] is True
    assert signoff["case_ref"] == GATE["dual_worker_case"]


def test_production_gray_band_closes_phase5f_contract(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    band = run_production_gray_band(tmp_path, validator)
    assert band.ok is True
    matrix = json.loads(Path("benchmarks/runtime_validation_matrix.json").read_text(encoding="utf-8"))
    case_ids = [item["id"] for item in matrix.get("cases", [])]
    assert "dual_disjoint_files" in case_ids


def test_runtime_matrix_dual_disjoint_case_passes_after_band(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    assert run_production_gray_band(tmp_path, validator).ok is True
    metrics = runtime_progress_metrics(tmp_path, validator)
    matrix = runtime_validation_matrix(tmp_path, metrics)
    dual = next(item for item in matrix["cases"] if item["id"] == "dual_disjoint_files")
    assert dual["ok"] is True
    assert dual["evidence"] == "production_gray_band"
