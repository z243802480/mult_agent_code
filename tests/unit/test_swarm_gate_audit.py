from pathlib import Path

from asteria_runtime.core.swarm_gate_audit import SwarmGateAuditor
from asteria_runtime.core.swarm_pipeline import run_maintainer_disjoint_gray_path
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_swarm_gate_audit_passes_on_gray_fixture(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / "run"
    result = run_maintainer_disjoint_gray_path(
        root=tmp_path / "repo",
        run_dir=run_dir,
        run_id="run-gray-1",
        validator=validator,
    )
    assert result.audit.ok is True
    assert result.dry_run["ok"] is True
    assert len(result.exports) == 2


def test_swarm_gate_audit_blocks_empty_run_dir(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    audit = SwarmGateAuditor(validator).evaluate_run_dir(tmp_path / "empty")
    assert audit.ok is False
    assert any(not check.ok for check in audit.checks)
