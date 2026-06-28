"""Prune local generated artifacts under a repo root (maintainer-only).

Touches only gitignored / runtime paths — never tracked source or docs.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune local Asteria runtime clutter.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without deleting")
    parser.add_argument(
        "--keep-validation-runs",
        type=int,
        default=20,
        help="Keep newest N validation_runs/validation-* directories",
    )
    parser.add_argument(
        "--validation-max-age-days",
        type=int,
        default=14,
        help="Also delete validation-* dirs older than this many days",
    )
    parser.add_argument(
        "--include-agent-cache",
        action="store_true",
        help="Remove .agent/ (large; rebuilt on next run)",
    )
    parser.add_argument(
        "--include-runs",
        action="store_true",
        help="Remove .asteria/runs/ (destructive; default keeps runs)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    removed: list[str] = []
    freed = 0

    def delete(path: Path) -> None:
        nonlocal freed
        if not path.exists():
            return
        size = _dir_size(path) if path.is_dir() else path.stat().st_size
        label = str(path.relative_to(root))
        if args.dry_run:
            print(f"would remove {label} ({_human_size(size)})")
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed.append(label)
        freed += size
        print(f"removed {label} ({_human_size(size)})")

    # Playwright / Studio test output
    delete(root / "studio" / "test-results")
    delete(root / "studio" / "playwright-report")
    delete(root / "studio" / "blob-report")

    asteria = root / ".asteria"
    for name in ("s7-signoff-workspace", "s13-clean-run-workspace", "s12-signoff-workspace"):
        delete(asteria / name)

    validation_root = asteria / "validation_runs"
    if validation_root.is_dir():
        runs = sorted(
            [p for p in validation_root.iterdir() if p.is_dir() and p.name.startswith("validation-")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.validation_max_age_days)
        for index, path in enumerate(runs):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if index >= args.keep_validation_runs or mtime < cutoff:
                delete(path)

    if args.include_runs:
        delete(asteria / "runs")

    if args.include_agent_cache:
        delete(root / ".agent")

    for cache in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        delete(root / cache)

    if args.dry_run:
        print("dry-run complete")
    else:
        print(f"prune complete: {len(removed)} path(s), ~{_human_size(freed)} reclaimed")


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _human_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{num}B"


if __name__ == "__main__":
    main()
