from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from asteria_runtime.core.candidate_workspace import CandidateWorkspace


def test_candidate_workspace_copies_safe_files_and_excludes_agent_state(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "src").mkdir()
    (source / "src" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "src" / "__pycache__").mkdir()
    (source / "src" / "__pycache__" / "tool.pyc").write_text("cache\n", encoding="utf-8")
    (source / ".asteria" / "secret.json").write_text("state\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")

    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    assert candidate.strategy == "temp_workspace"
    assert candidate.workspace_policy == "isolated_copy"
    assert candidate.backend_reason
    assert candidate.manifest_path
    assert candidate.manifest_path.exists()
    assert (candidate.root / "src" / "tool.py").exists()
    assert not (candidate.root / ".asteria").exists()
    assert not (candidate.root / ".agent").exists()
    assert not (candidate.root / ".git").exists()
    assert not (candidate.root / "src" / "__pycache__").exists()


def test_candidate_workspace_uses_git_worktree_for_clean_git_repo(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    try:
        subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "agent@example.test"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Agent Test"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "tool.py"], cwd=source, check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "commit", "-m", "seed"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git worktree unavailable: {exc}")

    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    assert candidate.strategy == "git_worktree"
    assert candidate.workspace_policy == "worktree"
    assert candidate.backend_reason
    assert "candidate branch" in candidate.backend_reason
    assert candidate.branch_name
    assert candidate.branch_name.startswith("asteria/candidate/task-0001-")
    assert "wt" in candidate.root.parts
    assert (candidate.root / "tool.py").exists()
    manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    assert manifest["strategy"] == "git_worktree"
    assert manifest["branch_name"] == candidate.branch_name


def test_candidate_workspace_uses_worktree_with_untracked_process_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "real_model_smoke_transcript.json").write_text("{}", encoding="utf-8")
    try:
        subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "agent@example.test"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Agent Test"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "tool.py"], cwd=source, check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "commit", "-m", "seed"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git worktree unavailable: {exc}")

    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    assert candidate.strategy == "git_worktree"
    assert candidate.branch_name
    candidate.discard()
    assert not candidate.root.exists()
    manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "discarded"


def test_candidate_workspace_promotes_only_changed_files(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    run_dir = source / ".asteria" / "runs" / "run-1"
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
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")

    with pytest.raises(ValueError, match="escapes workspace"):
        candidate.promote(["../escape.py"])


def test_failed_candidate_does_not_pollute_main_workspace(tmp_path: Path) -> None:
    """Golden trace: a candidate that writes and then discards leaves no artifacts in source."""
    source = tmp_path / "workspace"
    source.mkdir()
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    snapshot_before = set(p.name for p in source.iterdir())

    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")
    (candidate.root / "main.py").write_text("VALUE = 999\n", encoding="utf-8")
    (candidate.root / "side_effect.py").write_text("BAD = True\n", encoding="utf-8")
    candidate.discard()

    assert not candidate.root.exists()
    snapshot_after = set(p.name for p in source.iterdir())
    assert snapshot_before == snapshot_after
    assert (source / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (source / "side_effect.py").exists()
    manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "discarded"
