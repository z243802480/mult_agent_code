from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.swarm_gray_decision import run_gray_rollback_drill
from asteria_runtime.storage.schema_validator import SchemaValidator


GATE = json.loads(Path("benchmarks/phase5e_gray_decision_gate.json").read_text(encoding="utf-8"))


def test_phase5e_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "5"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["friction_gate"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()


def test_gray_rollback_drill_matches_gate_contract(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-phase5e"
    result = run_gray_rollback_drill(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-phase5e",
        validator=validator,
    )
    assert result.ok is True
    assert result.decision_point["metadata"]["kind"] == "swarm_gray_rollout"
    assert result.rollback_readiness.ready is True
