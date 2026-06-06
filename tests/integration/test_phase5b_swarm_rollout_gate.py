from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.swarm_pipeline import (
    run_maintainer_disjoint_gray_path,
    run_maintainer_real_disjoint_probe,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


GATE = json.loads(Path("benchmarks/phase5b_swarm_rollout_gate.json").read_text(encoding="utf-8"))
DEFAULT_POLICY = json.loads(Path("src/asteria_runtime/templates/policies.default.json").read_text(encoding="utf-8"))


def test_phase5b_rollout_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "5"
    assert GATE["wave"] == "2"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["plan"]).exists()
    assert Path(GATE["maintainer_script"]).exists()
    for brief in GATE["reference_briefs"]:
        assert Path(brief).exists()


def test_gray_path_still_fake_serial(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-gray-fake"
    result = run_maintainer_disjoint_gray_path(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-gray-fake",
        validator=validator,
        policy=DEFAULT_POLICY,
    )
    assert result.real_parallel is False
    assert result.spawn_plan["fake_path"] is True
    assert result.spawn_plan["scheduling_mode"] == "fake_serial"
    assert result.audit.ok is True


def test_real_disjoint_maintainer_probe_end_to_end(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-real-probe"
    result = run_maintainer_real_disjoint_probe(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-real-probe",
        validator=validator,
        policy=DEFAULT_POLICY,
    )
    probe = GATE["real_disjoint_probe"]
    required = probe["required_spawn"]
    assert result.real_parallel is True
    assert result.spawn_plan["scheduling_mode"] == required["scheduling_mode"]
    assert result.spawn_plan["fake_path"] is required["fake_path"]
    assert result.audit.ok is True
    for name in probe["required_evidence"]:
        assert (run_dir / name).exists(), f"missing {name}"
