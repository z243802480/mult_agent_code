from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_runtime.core.candidate_workspace import CandidateWorkspace
from agent_runtime.core.merge_gate import MergeGate


@dataclass
class FakeVerificationResult:
    ok: bool
    summary: str = "verification passed"


def _writable_task() -> dict:
    return {
        "task_id": "task-0001",
        "task_kind": "implementation",
        "write_scope": ["src/", "tests/"],
    }


def _readonly_task() -> dict:
    return {
        "task_id": "task-0002",
        "task_kind": "research",
    }


class TestMergeGateIsolation:
    """Tests that MergeGate blocks promotion when verification fails or
    files fall outside write_scope, and that CandidateWorkspace cleanup
    and git worktree failure paths work correctly."""

    def test_failed_candidate_not_promoted(self, tmp_path: Path) -> None:
        source = tmp_path / "workspace"
        run_dir = source / ".agent" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (source / "src").mkdir()
        (source / "src" / "mod.py").write_text("old", encoding="utf-8")

        task = _writable_task()
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)
        (candidate.root / "src" / "mod.py").write_text("new", encoding="utf-8")

        gate = MergeGate()
        result = gate.evaluate(
            task,
            changed_files=["src/mod.py"],
            verification_results=[FakeVerificationResult(ok=False, summary="test failed")],
        )

        assert not result.ok
        assert any("verification failed" in v for v in result.violations)
        assert result.promotable_files == []

        # Source should remain unchanged since promotion is blocked by the gate
        assert (source / "src" / "mod.py").read_text(encoding="utf-8") == "old"

    def test_changed_files_outside_write_scope_blocked(self, tmp_path: Path) -> None:
        source = tmp_path / "workspace"
        run_dir = source / ".agent" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (source / "secrets.yaml").write_text("key: value", encoding="utf-8")
        (source / "src").mkdir()
        (source / "src" / "mod.py").write_text("code", encoding="utf-8")

        task = _writable_task()
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)
        (candidate.root / "secrets.yaml").write_text("key: leaked", encoding="utf-8")
        (candidate.root / "src" / "mod.py").write_text("updated", encoding="utf-8")

        gate = MergeGate()
        result = gate.evaluate(
            task,
            changed_files=["secrets.yaml", "src/mod.py"],
            verification_results=[FakeVerificationResult(ok=True)],
        )

        assert not result.ok
        assert any("outside write_scope" in v for v in result.violations)
        assert result.promotable_files == []

    def test_successful_candidate_within_scope_promoted(self, tmp_path: Path) -> None:
        source = tmp_path / "workspace"
        run_dir = source / ".agent" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (source / "src").mkdir()
        (source / "src" / "mod.py").write_text("old", encoding="utf-8")

        task = _writable_task()
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)
        (candidate.root / "src" / "mod.py").write_text("new", encoding="utf-8")

        gate = MergeGate()
        result = gate.evaluate(
            task,
            changed_files=["src/mod.py"],
            verification_results=[FakeVerificationResult(ok=True)],
        )

        assert result.ok
        assert result.promotable_files == ["src/mod.py"]

        promoted = candidate.promote(result.promotable_files)
        assert promoted == ["src/mod.py"]
        assert (source / "src" / "mod.py").read_text(encoding="utf-8") == "new"

    def test_candidate_cleanup_removes_temp_workspace(self, tmp_path: Path) -> None:
        source = tmp_path / "workspace"
        run_dir = source / ".agent" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (source / "tool.py").write_text("v1", encoding="utf-8")

        task = _writable_task()
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)
        assert candidate.root.exists()

        candidate.discard()

        assert not candidate.root.exists()

    def test_git_worktree_no_merge_on_failure(self, tmp_path: Path) -> None:
        source = tmp_path / "workspace"
        source.mkdir()
        run_dir = source / ".agent" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (source / "tool.py").write_text("v1", encoding="utf-8")
        try:
            subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "agent@example.test"],
                cwd=source, check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Agent Test"],
                cwd=source, check=True, capture_output=True, text=True,
            )
            subprocess.run(["git", "add", "tool.py"], cwd=source, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "seed"],
                cwd=source, check=True, capture_output=True, text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.skip(f"git worktree unavailable: {exc}")

        task = _writable_task()
        candidate = CandidateWorkspace.create(source, run_dir, task["task_id"], task=task)

        assert candidate.strategy == "git_worktree"
        assert candidate.branch_name

        branch = candidate.branch_name
        (candidate.root / "tool.py").write_text("broken", encoding="utf-8")

        gate = MergeGate()
        result = gate.evaluate(
            task,
            changed_files=["tool.py"],
            verification_results=[FakeVerificationResult(ok=False, summary="tests failed")],
        )
        assert not result.ok

        # Source must remain untouched
        assert (source / "tool.py").read_text(encoding="utf-8") == "v1"

        # Verify the candidate branch exists on the source repo before discard
        branches_before = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=source, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch in branches_before

        candidate.discard()

        # Worktree should be removed
        assert not candidate.root.exists()

        # Branch should be cleaned up
        branches_after = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=source, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch not in branches_after

        # Source still untouched after discard
        assert (source / "tool.py").read_text(encoding="utf-8") == "v1"
