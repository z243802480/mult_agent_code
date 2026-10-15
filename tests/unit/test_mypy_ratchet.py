from __future__ import annotations

import subprocess

import pytest

from scripts import mypy_ratchet


def test_ratchet_uses_the_baseline_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.extend(args)
        return subprocess.CompletedProcess(args, 0, "Success: no issues found\n", "")

    monkeypatch.setattr(mypy_ratchet.subprocess, "run", fake_run)
    assert mypy_ratchet._run_mypy() == "Success: no issues found\n"
    assert seen[-5:] == ["--platform", "win32", "--python-version", "3.11", "src"]


def test_missing_mypy_cannot_be_reported_as_green(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mypy_ratchet.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 1, "", "No module named mypy"),
    )
    with pytest.raises(SystemExit, match="did not produce parseable type errors"):
        mypy_ratchet._run_mypy()
