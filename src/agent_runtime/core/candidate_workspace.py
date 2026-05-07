from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


EXCLUDED_NAMES = {
    ".agent",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class CandidateWorkspace:
    candidate_id: str
    root: Path
    source_root: Path
    strategy: str = "copy"

    @classmethod
    def create(cls, source_root: Path, run_dir: Path, task_id: str) -> "CandidateWorkspace":
        candidate_id = _candidate_id()
        candidate_root = run_dir / "cw" / task_id / _path_id(candidate_id)
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
        strategy = _create_workspace(source_root.resolve(), candidate_root)
        return cls(
            candidate_id=candidate_id,
            root=candidate_root,
            source_root=source_root.resolve(),
            strategy=strategy,
        )

    def promote(self, changed_files: list[str]) -> list[str]:
        promoted: list[str] = []
        for relative_path in sorted(set(changed_files)):
            source = (self.root / relative_path).resolve()
            target = (self.source_root / relative_path).resolve()
            try:
                source.relative_to(self.root)
                target.relative_to(self.source_root)
            except ValueError as exc:
                raise ValueError(f"Candidate path escapes workspace: {relative_path}") from exc
            if not source.exists() or not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            promoted.append(relative_path)
        return promoted


def _copy_workspace(source_root: Path, candidate_root: Path) -> None:
    candidate_root.mkdir(parents=True, exist_ok=True)
    for item in source_root.iterdir():
        if item.name in EXCLUDED_NAMES:
            continue
        target = candidate_root / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=_ignore_names)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _ignore_names(directory: str, names: list[str]) -> set[str]:
    del directory
    return {name for name in names if name in EXCLUDED_NAMES}


def _create_workspace(source_root: Path, candidate_root: Path) -> str:
    if _can_use_worktree(source_root):
        try:
            _run_git(source_root, "worktree", "add", "--detach", str(candidate_root), "HEAD")
            return "git_worktree"
        except (OSError, subprocess.SubprocessError):
            if candidate_root.exists():
                shutil.rmtree(candidate_root, ignore_errors=True)
    _copy_workspace(source_root, candidate_root)
    return "copy"


def _can_use_worktree(source_root: Path) -> bool:
    if not (source_root / ".git").exists():
        return False
    try:
        status = _run_git(source_root, "status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        return False
    # A dirty tree may include user edits that are not in HEAD, so copy preserves intent better.
    return not status.stdout.strip()


def _run_git(source_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )


def _candidate_id() -> str:
    return "candidate-" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")


def _path_id(candidate_id: str) -> str:
    return candidate_id.removeprefix("candidate-").replace("-", "")
