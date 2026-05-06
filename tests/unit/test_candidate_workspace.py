from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.core.candidate_workspace import CandidateWorkspace


def test_candidate_workspace_copies_safe_files_and_excludes_agent_state(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    run_dir = source / ".agent" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "src").mkdir()
    (source / "src" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "src" / "__pycache__").mkdir()
    (source / "src" / "__pycache__" / "tool.pyc").write_text("cache\n", encoding="utf-8")
    (source / ".agent" / "secret.json").write_text("state\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")

    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    assert (candidate.root / "src" / "tool.py").exists()
    assert not (candidate.root / ".agent").exists()
    assert not (candidate.root / ".git").exists()
    assert not (candidate.root / "src" / "__pycache__").exists()


def test_candidate_workspace_promotes_only_changed_files(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    run_dir = source / ".agent" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    (candidate.root / "extra.py").write_text("EXTRA = True\n", encoding="utf-8")

    promoted = candidate.promote(["tool.py"])

    assert promoted == ["tool.py"]
    assert (source / "tool.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not (source / "extra.py").exists()


def test_candidate_workspace_rejects_promote_paths_outside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    run_dir = source / ".agent" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    with pytest.raises(ValueError, match="escapes workspace"):
        candidate.promote(["../escape.py"])
