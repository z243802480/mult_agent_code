"""Phase 6 long-horizon maintainer smoke — S37–S40 contract tests + in-process band runners."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run Phase 6 long-horizon maintainer smoke.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "phase6_long_horizon_maintainer_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    steps: list[dict[str, object]] = []

    for rel in gate.get("contract_tests", []):
        steps.append(_run_pytest(root, str(rel)))

    steps.append(_run_in_process_bands(root))

    ok = all(step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "phase": gate.get("phase"),
        "steps": steps,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _run_in_process_bands(root: Path) -> dict[str, object]:
    from asteria_runtime.core.local_background_run import run_local_background_run_band
    from asteria_runtime.core.supervised_goal_loop import run_supervised_goal_loop_band
    from asteria_runtime.resources import schema_dir
    from asteria_runtime.storage.schema_validator import SchemaValidator

    validator = SchemaValidator(schema_dir())
    details: dict[str, object] = {}
    try:
        with tempfile.TemporaryDirectory() as supervised_tmp:
            supervised = run_supervised_goal_loop_band(
                Path(supervised_tmp),
                validator,
                max_slices=2,
            )
            details["supervised_goal_loop_band"] = supervised.to_dict()
        with tempfile.TemporaryDirectory() as background_tmp:
            background = run_local_background_run_band(Path(background_tmp), validator)
            details["local_background_run_band"] = background.to_dict()
        ok = bool(supervised.ok and background.ok)
    except Exception as exc:  # noqa: BLE001
        ok = False
        details["error"] = str(exc)
    return {
        "step": "in_process_bands",
        "ok": ok,
        "details": details,
    }


def _run_pytest(root: Path, target: str) -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", target, "-q"]
    completed = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "step": " ".join(cmd),
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _tail(text: str, lines: int = 8) -> str:
    parts = (text or "").strip().splitlines()
    if not parts:
        return ""
    return "\n".join(parts[-lines:])


if __name__ == "__main__":
    main()
