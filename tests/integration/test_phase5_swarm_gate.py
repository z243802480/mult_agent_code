from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.swarm_pipeline import run_maintainer_disjoint_gray_path
from asteria_runtime.storage.schema_validator import SchemaValidator


GATE = json.loads(Path("benchmarks/phase5_swarm_gate.json").read_text(encoding="utf-8"))


def test_phase5_swarm_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "5"
    assert Path(GATE["rfc"]).exists()
    assert Path(GATE["maintainer_script"]).exists()
    assert Path(GATE["signoff_report"]).parent.exists()
    for brief in GATE["reference_briefs"]:
        assert Path(brief).exists()
    assert "tests/integration/test_phase5_swarm_gate.py" in GATE["contract_tests"]


def test_phase5_maintainer_gray_path_end_to_end(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-phase5-gray"
    result = run_maintainer_disjoint_gray_path(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-phase5-gray",
        validator=validator,
    )
    assert result.audit.ok is True
    gray = GATE["gray_path"]
    for name in gray["required_evidence"]:
        assert (run_dir / name).exists(), f"missing {name}"
    assert gray["real_disjoint_write_workers"] is False
