"""Unified Phase 5 + steady maintainer pulse (S31–S33 holistic check)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run holistic steady + Phase 5 swarm pulse.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--skip-studio", action="store_true", help="Skip Studio smokes in integration check")
    args = parser.parse_args()

    root = args.root.resolve()
    gate = json.loads((root / "benchmarks" / "phase5e_gray_decision_gate.json").read_text(encoding="utf-8"))
    phase5d = json.loads((root / "benchmarks" / "phase5d_swarm_scenario_gate.json").read_text(encoding="utf-8"))
    friction = json.loads((root / "benchmarks" / "phase4_friction_gate.json").read_text(encoding="utf-8"))
    steps: list[dict[str, object]] = []

    steps.append(_run_python(root, "scripts/steady_iteration_check.py", ["--root", str(root), "--skip-b6"]))
    integration_cmd = ["--root", str(root)]
    if args.skip_studio:
        integration_cmd.append("--skip-studio")
    steps.append(_run_python(root, "scripts/swarm_integration_check.py", integration_cmd))
    steps.append(
        _run_python(root, "scripts/swarm_flag_rollout_check.py", ["--root", str(root), "--skip-probe"])
    )
    for rel in phase5d.get("contract_tests", []):
        steps.append(_run_pytest(root, str(rel)))
    for rel in gate.get("contract_tests", []):
        steps.append(_run_pytest(root, str(rel)))
    for rel in friction.get("contract_tests", []):
        steps.append(_run_pytest(root, str(rel)))
    steps.append(_run_shell(root, f"node {friction['studio_contract_smoke']}"))

    ok = all(step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "holistic_pulse": gate.get("holistic_pulse"),
        "real_provider_signoff": phase5d.get("real_provider_signoff"),
        "steps": steps,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _run_pytest(root: Path, target: str) -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", target, "-q"]
    return _run(root, target, cmd)


def _run_python(root: Path, script: str, extra: list[str]) -> dict[str, object]:
    cmd = [sys.executable, script, *extra]
    return _run(root, script, cmd)


def _run_shell(root: Path, command: str) -> dict[str, object]:
    return _run(root, command, command, shell=True)


def _run(root: Path, label: str, cmd: list[str] | str, shell: bool = False) -> dict[str, object]:
    completed = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def _tail(text: str, lines: int = 6) -> str:
    parts = (text or "").strip().splitlines()
    return "\n".join(parts[-lines:])


if __name__ == "__main__":
    main()
