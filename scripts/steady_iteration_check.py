"""Steady iteration pulse — one command for weekly maintainer green_checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 4 steady iteration pulse checks.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--skip-b6", action="store_true", help="Skip B6 Studio sim (needs models)")
    args = parser.parse_args()

    root = args.root.resolve()
    gate = json.loads((root / "benchmarks" / "phase4_steady_iteration_gate.json").read_text(encoding="utf-8"))

    steps: list[dict[str, object]] = []

    for rel in gate.get("contract_tests", []):
        steps.append(_run_pytest(root, str(rel)))

    steps.append(_run_python(root, "scripts/s15_wheel_install_smoke.py", ["--root", str(root)]))

    if not args.skip_b6:
        for command in gate.get("user_path_smokes", []):
            steps.append(_run_shell(root, str(command)))

    ok = all(step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "rhythm_doc": gate.get("rhythm_doc"),
        "steps": steps,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _run_pytest(root: Path, target: str) -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", target, "-q"]
    return _run(root, " ".join(cmd), cmd)


def _run_python(root: Path, script: str, extra: list[str]) -> dict[str, object]:
    cmd = [sys.executable, script, *extra]
    return _run(root, " ".join(cmd), cmd)


def _run_shell(root: Path, command: str) -> dict[str, object]:
    return _run(root, command, command, shell=True)


def _run(root: Path, label: str, cmd: str | list[str], shell: bool = False) -> dict[str, object]:
    completed = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        capture_output=True,
        shell=shell,
        check=False,
    )
    return {
        "step": label,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _tail(text: str, lines: int = 8) -> str:
    parts = (text or "").strip().splitlines()
    return "\n".join(parts[-lines:])


if __name__ == "__main__":
    main()
