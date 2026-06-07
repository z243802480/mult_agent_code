#!/usr/bin/env python3
"""Run Wave 5 L2 isolated parallel write production path probe (S65)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from asteria_runtime.core.orchestration_parallel_gray import (
    build_wave5_production_path_decision_point,
    evaluate_wave5_production_path_readiness,
    persist_orchestration_parallel_decision_point,
    run_orchestration_wave5_production_path_probe,
)
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.schema_validator import SchemaValidator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Wave 5 L2 isolated parallel write production path probe")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument(
        "--decision-id",
        default="decision-orchestration-parallel-0004",
        help="DecisionPoint id under .asteria/decisions/",
    )
    parser.add_argument(
        "--option",
        default="wave5_isolated_production_path",
        help="Option to resolve (default: wave5_isolated_production_path)",
    )
    parser.add_argument(
        "--write-decision",
        action="store_true",
        help="Persist Wave 5 DecisionPoint when readiness allows",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    validator = SchemaValidator(SCHEMA_DIR)
    policy = load_policy_config(root / ".asteria", validator)
    readiness = evaluate_wave5_production_path_readiness(root=root, policy=policy)

    decision_written = None
    if args.write_decision and readiness.ready_for_decision_point:
        decision_written = persist_orchestration_parallel_decision_point(
            agent_dir=root / ".asteria",
            validator=validator,
            decision_point=build_wave5_production_path_decision_point(
                run_id="orchestration-wave5-production-pulse",
                readiness=readiness,
            ),
        )

    try:
        result = run_orchestration_wave5_production_path_probe(
            repo_root=root,
            validator=validator,
            decision_id=args.decision_id,
            selected_option_id=args.option,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "readiness": readiness.to_dict(),
            "decision_point_written": str(decision_written) if decision_written else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    payload = {
        **result.to_dict(),
        "readiness": readiness.to_dict(),
        "decision_point_written": str(decision_written) if decision_written else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
