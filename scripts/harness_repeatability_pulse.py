"""Harness repeatability pulse — friction contract + optional B6 sample (Track H / S55)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from asteria_runtime.core.friction_contract import evaluate_friction


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Harness repeatability pulse for S55/S57.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--with-b6",
        action="store_true",
        help="Run one B6 sim and evaluate friction counters (needs real models)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    gate = json.loads((root / "benchmarks" / "phase4_friction_gate.json").read_text(encoding="utf-8"))
    thresholds = gate.get("thresholds") or {}

    steps: list[dict[str, object]] = []
    friction_sample: dict[str, int] | None = None

    contract = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_friction_contract.py", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    steps.append({"step": "friction_contract_tests", "ok": contract.returncode == 0})

    if args.with_b6:
        b6 = subprocess.run(
            ["node", "studio/scripts/b6-restricted-user-sim.mjs"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        friction_sample = _parse_b6_friction(b6.stdout)
        evaluation = evaluate_friction(friction_sample, thresholds=thresholds)
        steps.append(
            {
                "step": "b6_restricted_user_sim",
                "ok": b6.returncode == 0 and evaluation["ok"],
                "friction": friction_sample,
                "evaluation": evaluation,
                "stderr_tail": b6.stderr[-600:],
            }
        )
    else:
        steps.append(
            {
                "step": "b6_restricted_user_sim",
                "ok": True,
                "skipped": True,
                "note": "Use --with-b6 for real-model friction sample",
            }
        )

    ok = all(step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": "S55 harness repeatability pulse",
        "thresholds": thresholds,
        "friction_sample": friction_sample,
        "steps": steps,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _parse_b6_friction(stdout: str) -> dict[str, int]:
    match = re.search(r'"friction"\s*:\s*\{([^}]+)\}', stdout)
    if not match:
        return {"decide": 0, "debug": 0, "resume": 0}
    body = "{" + match.group(1) + "}"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"decide": 0, "debug": 0, "resume": 0}
    return {
        "decide": int(parsed.get("decide") or 0),
        "debug": int(parsed.get("debug") or 0),
        "resume": int(parsed.get("resume") or 0),
    }


if __name__ == "__main__":
    main()
