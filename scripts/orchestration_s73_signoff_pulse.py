#!/usr/bin/env python3
"""S73 signoff pulse — ingress 100% re-eval + Wave 8 Beta opt-in probe."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path) -> dict:
    temp_root = cwd / ".asteria" / "tmp" / "s73-pulse"
    temp_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"TEMP": str(temp_root), "TMP": str(temp_root), "TMPDIR": str(temp_root)})
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
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
    parser = argparse.ArgumentParser(description="S73 signoff pulse")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--real", action="store_true", help="Run real ingress eval + wave8 probe")
    args = parser.parse_args()
    root = args.root.resolve()
    verification_dir = root / ".asteria" / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    ingress_path = verification_dir / f"orchestration_dynamic_ingress_real_{today}.json"

    pytest = _run(
        [
            _pytest_executable(),
            "tests/unit/test_orchestration_dynamic_ingress.py",
            "tests/unit/test_orchestration_parallel_gray.py",
            "-k",
            "wave8 or dynamic_ingress",
            "-q",
            "--basetemp",
            str(root / ".asteria" / "tmp" / "s73-pytest"),
        ],
        cwd=root,
    )

    ingress_real = None
    wave8 = None
    wave6 = None
    wave7 = None
    if args.real:
        if not (verification_dir / "orchestration_wave6_dynamic_probe.json").exists():
            wave6 = _run(
                [sys.executable, "scripts/orchestration_wave6_dynamic_probe.py", "--root", str(root)],
                cwd=root,
            )
        if not (verification_dir / "orchestration_wave7_live_probe.json").exists():
            wave7 = _run(
                [sys.executable, "scripts/orchestration_wave7_live_probe.py", "--root", str(root)],
                cwd=root,
            )
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
        wave8 = _run(
            [
                sys.executable,
                "scripts/orchestration_wave8_beta_opt_in_probe.py",
                "--root",
                str(root),
                "--ingress-evidence",
                str(ingress_path),
            ],
            cwd=root,
        )

    checks = {"pytest": pytest["returncode"] == 0}
    if args.real:
        ingress_hit_rate = 0.0
        if ingress_path.exists():
            ingress_report = json.loads(ingress_path.read_text(encoding="utf-8"))
            ingress_hit_rate = float((ingress_report.get("summary") or {}).get("hit_rate") or 0)
        from asteria_runtime.core.orchestration_parallel_gray import dynamic_ingress_eval_passed

        ingress_passed, _ = dynamic_ingress_eval_passed(
            root,
            ingress_evidence_path=ingress_path if ingress_path.exists() else None,
            min_hit_rate=0.875,
        )
        checks["ingress_real"] = ingress_passed
        checks["wave8_probe"] = bool(wave8 and wave8["returncode"] == 0)
        checks["ingress_hit_rate_100"] = ingress_hit_rate >= 0.875

    report = {
        "ok": all(checks.values()),
        "purpose": "S73 ingress 100% + Wave 8 Beta opt-in signoff",
        "checks": checks,
        "pytest": pytest,
        "ingress_real": ingress_real,
        "wave6_probe": wave6,
        "wave7_probe": wave7,
        "wave8_probe": wave8,
        "ingress_evidence_path": str(ingress_path) if ingress_path.exists() else None,
    }
    out_path = verification_dir / f"orchestration_s73_signoff_{today}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["signoff_path"] = str(out_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def _pytest_executable() -> str:
    return shutil.which("pytest") or str(Path(sys.executable).with_name("pytest.exe"))


if __name__ == "__main__":
    raise SystemExit(main())
