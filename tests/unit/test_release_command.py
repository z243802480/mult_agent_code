from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.commands.release_command import ReleaseCommand

pytestmark = pytest.mark.contract


def test_release_command_passes_when_all_stages_skipped(tmp_path: Path) -> None:
    result = ReleaseCommand(
        root=tmp_path,
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_gate=True,
    ).run()

    assert result.ok
    assert result.status == "ready"
    assert result.stages == []
    assert result.failures == []


def test_release_command_blocks_without_acceptance_report(tmp_path: Path) -> None:
    result = ReleaseCommand(
        root=tmp_path,
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_gate=False,
        report_path=None,
    ).run()

    assert not result.ok
    assert result.status == "blocked"
    gate_stage = next(s for s in result.stages if s.name == "acceptance-gate")
    assert not gate_stage.ok
    assert "No acceptance report" in gate_stage.summary


def test_release_command_blocks_when_nonexistent_report_path(tmp_path: Path) -> None:
    result = ReleaseCommand(
        root=tmp_path,
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_gate=False,
        report_path=tmp_path / "does_not_exist.json",
    ).run()

    assert not result.ok
    gate_stage = next(s for s in result.stages if s.name == "acceptance-gate")
    assert not gate_stage.ok
    assert "No acceptance report" in gate_stage.summary


def test_release_command_to_dict_has_expected_keys(tmp_path: Path) -> None:
    result = ReleaseCommand(
        root=tmp_path,
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_gate=True,
    ).run()

    as_dict = result.to_dict()
    assert as_dict["schema_version"] == "0.1.0"
    assert as_dict["ok"] is True
    assert as_dict["status"] == "ready"
    assert as_dict["stages"] == []
    assert "root" in as_dict


def test_release_command_to_text_includes_status(tmp_path: Path) -> None:
    result = ReleaseCommand(
        root=tmp_path,
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_gate=True,
    ).run()

    text = result.to_text()
    assert "Release Gate" in text
    assert "ready" in text
