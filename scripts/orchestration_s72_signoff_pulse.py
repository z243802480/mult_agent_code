#!/usr/bin/env python3
"""S72 signoff pulse — unit checks + optional real ingress eval evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path) -> dict:
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="S72 orchestration signoff pulse")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run strong-model dynamic ingress eval and write verification evidence",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    verification_dir = root / ".asteria" / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)

    pytest = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_orchestration_run_command.py",
            "tests/unit/test_orchestration_live_provider.py",
            "tests/unit/test_orchestration_dynamic_ingress.py",
            "-q",
        ],
        cwd=root,
    )
    setup_pulse = _run(
        [sys.executable, "scripts/orchestration_dynamic_ingress_pulse.py", "--root", str(root)],
        cwd=root,
    )
    orch_dry = _run(
        [
            sys.executable,
            "-m",
            "asteria_runtime.cli",
            "orchestration",
            "run",
            "--root",
            str(root),
            "--manifest",
            str(root / "benchmarks" / "orchestration_s72_ingress_manifest.json"),
            "--no-resume",
            "--json",
        ],
        cwd=root,
    )

    ingress_real = None
    ingress_path = None
    if args.real:
        ingress_path = verification_dir / f"orchestration_dynamic_ingress_real_{date.today().strftime('%Y%m%d')}.json"
        ingress_real = _run(
            [
                sys.executable,
                "scripts/orchestration_dynamic_ingress_pulse.py",
                "--root",
                str(root),
                "--real",
                "--summary-json",
                str(ingress_path),
            ],
            cwd=root,
        )

    checks = {
        "pytest": pytest["returncode"] == 0,
        "ingress_setup": setup_pulse["returncode"] == 0,
        "orchestration_dry": orch_dry["returncode"] == 0,
    }
    if args.real:
        checks["ingress_real"] = bool(ingress_real and ingress_real["returncode"] == 0)

    report = {
        "ok": all(checks.values()),
        "purpose": "S72 orchestration signoff pulse",
        "checks": checks,
        "pytest": pytest,
        "ingress_setup": setup_pulse,
        "orchestration_dry": orch_dry,
        "ingress_real": ingress_real,
        "ingress_evidence_path": str(ingress_path) if ingress_path else None,
    }
    out_path = verification_dir / f"orchestration_s72_signoff_{date.today().strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["signoff_path"] = str(out_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
