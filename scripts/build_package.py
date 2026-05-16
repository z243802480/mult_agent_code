from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local agent-runtime wheel artifacts.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--dist-dir", type=Path, default=None, help="Output directory")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing wheel artifacts from the output directory before building",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    dist_dir = (args.dist_dir or root / "dist").resolve()
    if not (root / "pyproject.toml").exists():
        raise SystemExit(f"pyproject.toml not found under {root}")

    dist_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        _clean_dist(dist_dir)

    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(dist_dir),
        str(root),
    ]
    completed = subprocess.run(command, cwd=root, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    wheels = sorted(dist_dir.glob("agent_runtime-*.whl"))
    if not wheels:
        raise SystemExit(f"wheel build did not produce agent_runtime artifact in {dist_dir}")

    latest = max(wheels, key=lambda path: path.stat().st_mtime)
    print(f"Built wheel: {latest}")


def _clean_dist(dist_dir: Path) -> None:
    for path in dist_dir.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        elif path.suffix in {".whl", ".gz", ".zip"}:
            path.unlink()


if __name__ == "__main__":
    main()
