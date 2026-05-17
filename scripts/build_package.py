from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local asteria-runtime wheel artifacts.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--dist-dir", type=Path, default=None, help="Output directory")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing wheel artifacts from the output directory before building",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Build only the asteria-runtime wheel and skip runtime dependency wheels",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    dist_dir = (args.dist_dir or root / "dist").resolve()
    if not (root / "pyproject.toml").exists():
        raise SystemExit(f"pyproject.toml not found under {root}")

    dist_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        _clean_dist(dist_dir)
        _clean_build(root / "build", root)

    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--wheel-dir",
        str(dist_dir),
        str(root),
    ]
    if args.no_deps:
        command.insert(4, "--no-deps")
    completed = subprocess.run(command, cwd=root, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    wheels = sorted(dist_dir.glob("asteria_runtime-*.whl"))
    if not wheels:
        raise SystemExit(f"wheel build did not produce asteria_runtime artifact in {dist_dir}")

    latest = max(wheels, key=lambda path: path.stat().st_mtime)
    print(f"Built wheel: {latest}")


def _clean_dist(dist_dir: Path) -> None:
    for path in dist_dir.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        elif path.suffix in {".whl", ".gz", ".zip"}:
            path.unlink()


def _clean_build(build_dir: Path, root: Path) -> None:
    if not build_dir.exists():
        return
    resolved_build = build_dir.resolve()
    resolved_root = root.resolve()
    if not resolved_build.is_relative_to(resolved_root):
        raise SystemExit(f"refusing to remove build directory outside repository: {resolved_build}")
    shutil.rmtree(resolved_build)


if __name__ == "__main__":
    main()
