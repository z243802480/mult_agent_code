from __future__ import annotations

import json
from pathlib import Path

import pytest

from unittest.mock import patch

from asteria_runtime.commands.background_run_command import BackgroundRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.core.local_background_run import (
    BACKGROUND_RUN_EVIDENCE_FILE,
    run_local_background_run_band,
)
from asteria_runtime.storage.schema_validator import SchemaValidator

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase6f_local_background_run_gate.json").read_text(encoding="utf-8")
)


def test_phase6f_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "6"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    scope = GATE["background_scope"]
    assert scope["cloud_vm"] is False
    assert scope["local_subprocess"] is True


def test_local_background_run_band_closes_phase6f_contract(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    band = run_local_background_run_band(tmp_path, validator)
    assert band.ok is True
    assert band.run_id
    evidence = (
        tmp_path / ".asteria" / "runs" / band.run_id / BACKGROUND_RUN_EVIDENCE_FILE
    )
    assert evidence.exists()


def test_background_start_and_status_projection(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    goal = "Run helper in background"

    class _FakeProcess:
        pid = 515151
        returncode: int | None = None

    def fake_spawn(command: list[str], **kwargs: object) -> _FakeProcess:
        return _FakeProcess()

    from asteria_runtime.core.local_background_run import start_local_background_run

    entry = start_local_background_run(
        tmp_path,
        goal,
        SchemaValidator(Path.cwd() / "schemas"),
        spawn=fake_spawn,
    )
    assert entry["pid"] == 515151
    assert entry["status"] == "starting"

    with patch("asteria_runtime.core.local_background_run._pid_is_alive", return_value=True):
        status = BackgroundRunCommand(tmp_path, action="status").run()
        payload = StatusCommand(tmp_path).run().to_dict()
    assert status.ok is True
    assert status.projection is not None
    assert status.projection["local_subprocess"] is True
    assert status.projection["cloud_vm"] is False
    background = payload["background_runs"]
    assert background["running_count"] >= 1
    assert background["badge_status"] == "running"
