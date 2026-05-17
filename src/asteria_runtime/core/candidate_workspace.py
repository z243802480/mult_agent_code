from __future__ import annotations

import os
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from asteria_runtime.core.sandbox_backend import SandboxBackendPlan, SandboxBackendSelector


EXCLUDED_NAMES = {
    ".asteria",
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
    branch_name: str | None = None
    manifest_path: Path | None = None

    @classmethod
    def from_promotion(cls, source_root: Path, run_dir: Path, promotion: dict) -> "CandidateWorkspace":
        candidate_id = str(promotion["candidate_id"])
        manifest_path = run_dir / "candidates" / f"{candidate_id}.json"
        return cls(
            candidate_id=candidate_id,
            root=Path(str(promotion["workspace"])),
            source_root=source_root.resolve(),
            strategy=str(promotion.get("strategy") or "temp_workspace"),
            workspace_policy=str(promotion.get("workspace_policy") or "isolated_copy"),
            backend_reason=str(promotion.get("backend_reason") or ""),
            branch_name=promotion.get("branch_name"),
            manifest_path=manifest_path if manifest_path.exists() else None,
        )

    @classmethod
    def create(
        cls, source_root: Path, run_dir: Path, task_id: str, task: dict | None = None
    ) -> "CandidateWorkspace":
        candidate_id = _candidate_id()
        selector = SandboxBackendSelector()
        plan = (
            selector.select_for_task(source_root.resolve(), task)
            if task
            else selector.select_for_workspace(source_root.resolve())
        )
        branch_name = (
            _candidate_branch(task_id, candidate_id) if plan.backend == "git_worktree" else None
        )
        candidate_root = _candidate_root(run_dir, task_id, candidate_id, plan.backend)
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
        strategy = _create_workspace(source_root.resolve(), candidate_root, plan, branch_name)
        manifest_path = _write_manifest(
            run_dir=run_dir,
            candidate_id=candidate_id,
            task_id=task_id,
            candidate_root=candidate_root,
            strategy=strategy,
            workspace_policy=plan.workspace_policy if strategy == plan.backend else "isolated_copy",
            backend_reason=plan.reason,
            branch_name=branch_name if strategy == "git_worktree" else None,
        )
        return cls(
            candidate_id=candidate_id,
            root=candidate_root,
            source_root=source_root.resolve(),
            strategy=strategy,
            workspace_policy=plan.workspace_policy if strategy == plan.backend else "isolated_copy",
            backend_reason=plan.reason,
            branch_name=branch_name if strategy == "git_worktree" else None,
            manifest_path=manifest_path,
        )

    def promote(self, changed_files: list[str]) -> list[str]:
        self.validate_promotion_ready(changed_files)
        promoted: list[str] = []
        candidate_root = self.root.resolve()
        source_root = self.source_root.resolve()
        for relative_path in sorted(set(changed_files)):
            source = (candidate_root / relative_path).resolve()
            target = (source_root / relative_path).resolve()
            if not _is_within(source, candidate_root) or not _is_within(target, source_root):
                raise ValueError(f"Candidate path escapes workspace: {relative_path}")
            if not source.exists() or not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            promoted.append(relative_path)
        _update_manifest(self.manifest_path, {"status": "promoted"})
        return promoted

    def validate_promotion_ready(self, changed_files: list[str]) -> None:
        candidate_root = self.root.resolve()
        source_root = self.source_root.resolve()
        if not candidate_root.exists():
            raise RuntimeError(f"Candidate workspace is missing: {candidate_root}")
        if not changed_files:
            raise RuntimeError("Candidate promotion has no promotable files.")
        for relative_path in sorted(set(changed_files)):
            source = (candidate_root / relative_path).resolve()
            target = (source_root / relative_path).resolve()
            if not _is_within(source, candidate_root) or not _is_within(target, source_root):
                raise ValueError(f"Candidate path escapes workspace: {relative_path}")
            if not source.exists() or not source.is_file():
                raise RuntimeError(f"Promotable file is missing from candidate: {relative_path}")
        if self.strategy == "git_worktree":
            self._validate_git_worktree(changed_files)

    def discard(self) -> None:
        root = self.root.resolve()
        if self.strategy == "git_worktree" and root.exists():
            try:
                _run_git(self.source_root, "worktree", "remove", "--force", str(root))
                _run_git(self.source_root, "worktree", "prune")
                if self.branch_name:
                    _delete_branch_if_exists(self.source_root, self.branch_name)
                _update_manifest(
                    self.manifest_path, {"status": "discarded", "cleanup": "worktree_removed"}
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        _update_manifest(
            self.manifest_path, {"status": "discarded", "cleanup": "directory_removed"}
        )

    def _validate_git_worktree(self, changed_files: list[str]) -> None:
        _run_git(self.source_root, "worktree", "list")
        source_status = _run_git_status(self.source_root, changed_files)
        if source_status:
            raise RuntimeError(
                "Source workspace has uncommitted changes in promotable paths: "
                + "; ".join(source_status)
            )
        worktree_status = _run_git_status(self.root, changed_files)
        unmerged = [
            line
            for line in worktree_status
            if len(line) >= 2 and ("U" in line[:2] or line[:2] in {"AA", "DD"})
        ]
        if unmerged:
            raise RuntimeError("Candidate worktree has unresolved conflicts: " + "; ".join(unmerged))


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
    branch_name: str | None,
) -> str:
    if plan.backend == "git_worktree":
        try:
            if branch_name:
                _run_git(
                    source_root, "worktree", "add", "-b", branch_name, str(candidate_root), "HEAD"
                )
            else:
                _run_git(source_root, "worktree", "add", "--detach", str(candidate_root), "HEAD")
            return "git_worktree"
        except (OSError, subprocess.SubprocessError):
            if candidate_root.exists():
                shutil.rmtree(candidate_root, ignore_errors=True)
    _copy_workspace(source_root, candidate_root)
    return "temp_workspace"


def _candidate_root(run_dir: Path, task_id: str, candidate_id: str, backend: str) -> Path:
    del task_id
    bucket = "wt" if backend == "git_worktree" else "cw"
    return run_dir / bucket / _short_path_id(candidate_id)


def _write_manifest(
    *,
    run_dir: Path,
    candidate_id: str,
    task_id: str,
    candidate_root: Path,
    strategy: str,
    workspace_policy: str,
    backend_reason: str,
    branch_name: str | None,
) -> Path:
    manifest_dir = run_dir / "candidates"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{candidate_id}.json"
    manifest = {
        "schema_version": "0.1.0",
        "candidate_id": candidate_id,
        "task_id": task_id,
        "workspace": str(candidate_root),
        "strategy": strategy,
        "workspace_policy": workspace_policy,
        "backend_reason": backend_reason,
        "branch_name": branch_name,
        "status": "active",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def _update_manifest(manifest_path: Path | None, updates: dict[str, str]) -> None:
    if manifest_path is None or not manifest_path.exists():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data.update(updates)
    manifest_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _run_git(source_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )


def _run_git_status(source_root: Path, paths: list[str]) -> list[str]:
    completed = _run_git(
        source_root,
        "status",
        "--porcelain",
        "--",
        *sorted(set(paths)),
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _delete_branch_if_exists(source_root: Path, branch_name: str) -> None:
    completed = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode == 0:
        _run_git(source_root, "branch", "-D", branch_name)


def _is_within(path: Path, root: Path) -> bool:
    normalized_path = os.path.normcase(os.path.abspath(path))
    normalized_root = os.path.normcase(os.path.abspath(root))
    return os.path.commonpath([normalized_path, normalized_root]) == normalized_root


def _candidate_id() -> str:
    return "candidate-" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")


def _path_id(candidate_id: str) -> str:
    return candidate_id.removeprefix("candidate-").replace("-", "")


def _short_path_id(candidate_id: str) -> str:
    return _path_id(candidate_id)[9:]


def _candidate_branch(task_id: str, candidate_id: str) -> str:
    safe_task = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in task_id)
    return f"asteria/candidate/{safe_task}-{_path_id(candidate_id)}"
