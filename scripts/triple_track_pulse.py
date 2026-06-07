"""Triple-track maintainer pulse — F2 friction + Harness + Beta pack + steady gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run triple-track maintainer pulse.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--skip-b6", action="store_true", help="Skip B6 sim in steady track")
    args = parser.parse_args()

    root = args.root.resolve()
    tracks: dict[str, object] = {}

    tracks["A_steady"] = _run_python(
        root,
        "scripts/steady_iteration_check.py",
        ["--root", str(root), *(["--skip-b6"] if args.skip_b6 else [])],
    )
    tracks["F2_friction"] = _run_python(root, "scripts/beta_friction_aggregate.py", ["--root", str(root)])
    tracks["P_beta_pack"] = _run_python(root, "scripts/beta_task_pack_check.py", ["--root", str(root)])
    tracks["H_friction_contract"] = _run_pytest(root, "tests/unit/test_friction_contract.py")
    tracks["H_repeatability"] = _run_python(
        root,
        "scripts/harness_repeatability_pulse.py",
        ["--root", str(root)],
    )

    steps = list(tracks.values())
    ok = all(isinstance(step, dict) and step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": "Triple-track pulse (A steady + F2 friction + P pack + H contract)",
        "plan": "docs/zh/plans/TRIPLE_TRACK_MAINT_PLAN.md",
        "active_slice": "S55",
        "tracks": tracks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _run_python(root: Path, script: str, extra: list[str]) -> dict[str, object]:
    cmd = [sys.executable, script, *extra]
    completed = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "track": script,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-1500:],
        "stderr_tail": completed.stderr[-800:],
    }


def _run_pytest(root: Path, target: str) -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", target, "-q"]
    completed = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "track": target,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-800:],
        "stderr_tail": completed.stderr[-400:],
    }


if __name__ == "__main__":
    main()
