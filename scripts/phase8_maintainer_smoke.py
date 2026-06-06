"""Phase 8 Long Task Intelligence maintainer smoke — S41–S44 contract tests + band runners."""

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
    parser = argparse.ArgumentParser(description="Run Phase 8 maintainer smoke.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "phase8_long_task_intelligence_gate.json"
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
    from asteria_runtime.core.remote_background_adapter import run_remote_background_stub_band
    from asteria_runtime.resources import schema_dir
    from asteria_runtime.storage.schema_validator import SchemaValidator

    validator = SchemaValidator(schema_dir())
    details: dict[str, object] = {}
    try:
        with tempfile.TemporaryDirectory() as remote_tmp:
            remote = run_remote_background_stub_band(Path(remote_tmp), validator)
            details["remote_background_stub_band"] = remote.to_dict()
        ok = bool(remote.ok)
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
