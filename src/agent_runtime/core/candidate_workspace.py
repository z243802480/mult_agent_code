from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_runtime.core.sandbox_backend import SandboxBackendPlan, SandboxBackendSelector


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
    strategy: str = "temp_workspace"
    workspace_policy: str = "isolated_copy"
    backend_reason: str = ""

    @classmethod
    def create(cls, source_root: Path, run_dir: Path, task_id: str) -> "CandidateWorkspace":
        candidate_id = _candidate_id()
        candidate_root = run_dir / "cw" / task_id / _path_id(candidate_id)
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
        plan = SandboxBackendSelector().select_for_workspace(source_root.resolve())
        strategy = _create_workspace(source_root.resolve(), candidate_root, plan)
        return cls(
            candidate_id=candidate_id,
            root=candidate_root,
            source_root=source_root.resolve(),
            strategy=strategy,
            workspace_policy=plan.workspace_policy if strategy == plan.backend else "isolated_copy",
            backend_reason=plan.reason,
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


def _create_workspace(
    source_root: Path,
    candidate_root: Path,
    plan: SandboxBackendPlan,
) -> str:
    if plan.backend == "git_worktree":
        try:
            _run_git(source_root, "worktree", "add", "--detach", str(candidate_root), "HEAD")
            return "git_worktree"
        except (OSError, subprocess.SubprocessError):
            if candidate_root.exists():
                shutil.rmtree(candidate_root, ignore_errors=True)
    _copy_workspace(source_root, candidate_root)
    return "temp_workspace"


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
