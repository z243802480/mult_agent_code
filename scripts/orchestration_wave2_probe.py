#!/usr/bin/env python3
"""Run Wave 2 maintainer-isolated parallel_writes probe (S64)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from asteria_runtime.core.orchestration_parallel_gray import run_orchestration_wave2_band
from asteria_runtime.storage.schema_validator import SchemaValidator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Wave 2 orchestration parallel gray probe")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument(
        "--decision-id",
        default="decision-orchestration-parallel-0001",
        help="DecisionPoint id under .asteria/decisions/",
    )
    parser.add_argument(
        "--option",
        default="wave2_maintainer_probe",
        help="Option to resolve (default: wave2_maintainer_probe)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Isolated workspace (default: temp dir, removed after run)",
    )
    args = parser.parse_args()

    validator = SchemaValidator(SCHEMA_DIR)
    try:
        result = run_orchestration_wave2_band(
            repo_root=args.root,
            validator=validator,
            decision_id=args.decision_id,
            selected_option_id=args.option,
            isolated_workspace=args.workspace,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = result.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
