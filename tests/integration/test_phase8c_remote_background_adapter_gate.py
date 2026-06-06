from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.background_run_command import BackgroundRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.remote_background_adapter import run_remote_background_stub_band
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase8c_remote_background_adapter_gate.json").read_text(encoding="utf-8")
)


def test_phase8c_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "8"
    assert Path(GATE["depends_on_gate"]).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    scope = GATE["adapter_scope"]
    assert scope["cloud_vm_deferred"] is True
    assert scope["remote_available"] is False


def test_background_start_remote_registers_deferred_entry(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    result = BackgroundRunCommand(tmp_path, action="start", goal="remote intent", remote=True).run()
    assert result.background_run_id
    assert result.status == "deferred"
    assert result.projection is None
    status = BackgroundRunCommand(tmp_path, action="status").run()
    assert status.projection is not None
    assert status.projection.get("remote_adapter") == "stub"
    assert status.projection.get("remote_available") is False


def test_remote_background_stub_band(tmp_path: Path) -> None:
    validator = SchemaValidator(schema_dir())
    band = run_remote_background_stub_band(tmp_path, validator)
    assert band.ok is True
