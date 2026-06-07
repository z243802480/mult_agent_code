"""Orchestration parallel gray maintainer pulse (S64)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_parallel_gray import (
    build_orchestration_parallel_decision_point,
    evaluate_orchestration_parallel_readiness,
    persist_orchestration_parallel_decision_point,
)
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.schema_validator import SchemaValidator


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Orchestration parallel gray readiness pulse.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--spawn-evidence", type=Path, default=None)
    parser.add_argument("--route-evidence", type=Path, default=None)
    parser.add_argument(
        "--gray-drill-ok",
        action="store_true",
        help="Assert S32 gray rollback drill already passed (maintainer signoff)",
    )
    parser.add_argument(
        "--write-decision",
        action="store_true",
        help="Persist DecisionPoint under .asteria/decisions/ when readiness allows",
    )
    parser.add_argument("--summary-json", type=Path, default=None)
    args = parser.parse_args()

    root = args.root.resolve()
    if not (root / ".asteria").exists():
        InitCommand(root).run()

    validator = SchemaValidator(Path(__file__).resolve().parents[1] / "schemas")
    policy = load_policy_config(root / ".asteria", validator)
    readiness = evaluate_orchestration_parallel_readiness(
        root=root,
        policy=policy,
        spawn_evidence_path=args.spawn_evidence,
        route_evidence_path=args.route_evidence,
        gray_drill_ok=True if args.gray_drill_ok else None,
    )

    decision_point = build_orchestration_parallel_decision_point(
        run_id="orchestration-parallel-gray-pulse",
        readiness=readiness,
    )
    decision_path = None
    if args.write_decision and readiness.ready_for_decision_point:
        decision_path = persist_orchestration_parallel_decision_point(
            agent_dir=root / ".asteria",
            validator=validator,
            decision_point=decision_point,
        )

    report = {
        "ok": readiness.ready_for_decision_point,
        "purpose": "S64 orchestration parallel gray readiness (Wave 2 probe gate)",
        "brief": "benchmarks/reference_briefs/S64-orchestration-parallel-gray-rollout.md",
        "readiness": readiness.to_dict(),
        "decision_point_id": decision_point.get("decision_id"),
        "decision_point_written": str(decision_path) if decision_path else None,
        "recommended_option": decision_point.get("recommended_option_id"),
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if readiness.ready_for_decision_point else 1)


if __name__ == "__main__":
    main()
