"""Stat-level workspace change scan — disk truth for the completion contract.

Dogfood run-20260718-0001: the doer, denied by tool-layer write scope, wrote four files
through ``run_command`` (one ``python -c``); the contract's changed-file ledger (tool-layer
``artifact_refs`` only) stayed empty and every round was judged blocked while the feature sat
finished on disk. The contract now consults the disk: changes inside ``write_scope`` count as
real progress regardless of which path produced them; changes outside it are disclosed
(``unscoped_changed_files``) instead of staying invisible. Preventing the bypass itself is the
OS sandbox's job (ADR-0030), not this scan's — this is honest accounting, not a new gate.

The scan is stat-level (mtime_ns + size), never reads file contents, prunes well-known junk
directories, and bails out (returns ``None``) on oversized workspaces so a huge repo cannot
turn every task into a directory walk.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directories whose churn is build/runtime noise, not authored change. ``.asteria`` is the
# runtime's own state; ``.git`` is protected wholesale (AGENTS §10).
_SKIP_DIRS = {
    ".git",
    ".asteria",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".idea",
    ".vscode",
}
_SKIP_SUFFIXES = {".pyc", ".pyo"}

# Bail-out bound: beyond this the walk itself becomes a per-task tax; the feature degrades to
# the tool-ledger-only behaviour instead of slowing every task down.
MAX_SCAN_FILES = 5000

Snapshot = dict[str, tuple[int, int]]


def snapshot_workspace(root: Path, max_files: int = MAX_SCAN_FILES) -> Snapshot | None:
    """Map of relative posix path -> (mtime_ns, size), or None when the workspace is too big."""
    base = Path(root)
    if not base.is_dir():
        return None
    entries: Snapshot = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        for name in filenames:
            if Path(name).suffix.lower() in _SKIP_SUFFIXES:
                continue
            full = Path(dirpath) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            rel = full.relative_to(base).as_posix()
            entries[rel] = (stat.st_mtime_ns, stat.st_size)
            if len(entries) > max_files:
                return None
    return entries


def changed_paths(before: Snapshot | None, after: Snapshot | None) -> list[str]:
    """Created, modified, and deleted paths between two snapshots (sorted, deduplicated)."""
    if before is None or after is None:
        return []
    changed = {path for path, sig in after.items() if before.get(path) != sig}
    changed.update(path for path in before if path not in after)
    return sorted(changed)
