"""S15 wheel install smoke — lightweight §3.1 path for Beta hardening."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify asteria-runtime wheel install path (S15 C2).")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--keep", action="store_true", help="Keep temp venv/workspace for inspection")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a clean wheel rebuild before the smoke (required for release sign-off; "
        "otherwise a stale wheel left in dist/ would be reused).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    dist_dir = root / "dist"
    wheels = sorted(dist_dir.glob("asteria_runtime-*.whl"))
    if args.rebuild or not wheels:
        build_command = [sys.executable, str(root / "scripts" / "build_package.py"), "--root", str(root), "--no-deps"]
        if args.rebuild:
            build_command.append("--clean")
        subprocess.run(build_command, check=True)
        wheels = sorted(dist_dir.glob("asteria_runtime-*.whl"))
    wheel = max(wheels, key=lambda item: item.stat().st_mtime)

    temp_root = root / ".asteria" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="asteria-s15-wheel-", dir=temp_root))
    venv_dir = base / "venv"
    workspace = base / "workspace"
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        venv_python = _venv_python(venv_dir)
        pip = [str(venv_python), "-m", "pip", "install", "--quiet"]
        # Install the wheel directly (same as beta_install.ps1); deps e.g. tzdata come from PyPI.
        subprocess.run([*pip, str(wheel)], check=True)
        subprocess.run([*pip, "pytest"], check=True)

        steps = [
            ([str(venv_python), "-m", "asteria_runtime", "version", "--json"], "version"),
            ([str(venv_python), "-m", "asteria_runtime", "init", "--root", str(workspace)], "init"),
            ([str(venv_python), "-m", "asteria_runtime", "doctor", "--root", str(workspace), "--json"], "doctor"),
        ]
        report: dict[str, object] = {"ok": True, "wheel": str(wheel), "base": str(base), "steps": {}}
        for command, name in steps:
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                raise SystemExit(
                    f"{name} failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
                )
            payload = completed.stdout.strip()
            if payload.startswith("{"):
                report["steps"][name] = json.loads(payload)
            else:
                report["steps"][name] = payload.splitlines()[:5]

        version = report["steps"].get("version")
        if isinstance(version, dict) and not version.get("version"):
            raise SystemExit(f"installed version missing: {version}")

        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if args.keep:
            print(f"kept temp dir: {base}", file=sys.stderr)
        else:
            shutil.rmtree(base, ignore_errors=True)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


if __name__ == "__main__":
    main()
