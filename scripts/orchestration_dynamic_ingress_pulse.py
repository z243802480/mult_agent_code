"""Orchestration dynamic ingress maintainer pulse — S70 strong route eval."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_parallel_gray import (
    PRODUCTION_PATH_POLICY_KEY,
    set_isolated_parallel_write_production_path,
    set_orchestration_dynamic_workflows_gray,
)
from asteria_runtime.route_worker import handle_route_request
from asteria_runtime.storage.schema_validator import SchemaValidator


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="S70 L3 dynamic orchestration ingress pulse.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run strong model ingress cases (maintainer eval)",
    )
    parser.add_argument("--summary-json", type=Path, default=None, help="Write report JSON")
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "orchestration_dynamic_ingress_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    workspace = _prepare_dynamic_ingress_workspace(root)

    if not args.real:
        report = {
            "ok": True,
            "purpose": gate.get("purpose"),
            "mode": "setup_only",
            "workspace": str(workspace),
            "dynamic_workflows_gray": True,
            "summary": {"case_count": len(gate.get("cases") or []), "note": "Use --real for strong model eval; CI uses pytest."},
            "checks": {"workspace_ready": True, "gate_present": gate_path.exists()},
        }
        if args.summary_json:
            args.summary_json.parent.mkdir(parents=True, exist_ok=True)
            args.summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    mode = "model"
    cases = list(gate.get("cases") or [])
    if not cases:
        raise SystemExit("no ingress cases configured")

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    hits = 0

    for case in cases:
        started = time.perf_counter()
        payload = {
            "id": case.get("id"),
            "op": "route",
            "root": str(workspace),
            "message": case.get("message"),
            "mode": "auto",
            "rules_only": False,
            "router_mode": mode,
            "include_catalog": False,
        }
        response = handle_route_request(payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)

        capability_id = response.get("capability_id")
        accepted = _accepted_capabilities(case)
        ok = response.get("ok") is True and capability_id in accepted
        if ok:
            hits += 1

        results.append(
            {
                "id": case.get("id"),
                "ok": ok,
                "capability_id": capability_id,
                "source": response.get("source"),
                "elapsed_ms": round(elapsed_ms, 2),
                "expect_capability": case.get("expect_capability"),
                "accept_capabilities": sorted(accepted),
                "router_mode": mode,
                "reason": response.get("reason"),
            }
        )

    case_count = max(len(results), 1)
    hit_rate = hits / case_count
    max_latency_ms = max(latencies) if latencies else 0.0
    thresholds = dict(gate.get("real_thresholds" if args.real else "thresholds") or {})

    checks = {
        "hit_rate": hit_rate >= float(thresholds.get("min_hit_rate", 0.8)),
        "latency": max_latency_ms
        <= float(thresholds.get("max_per_case_latency_ms") or thresholds.get("max_inprocess_latency_ms") or 45000),
        "dynamic_gray_enabled": True,
    }
    ok = all(checks.values())

    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "brief": gate.get("brief"),
        "mode": mode,
        "eval_tier": "strong" if args.real else "strong_ci_stub",
        "workspace": str(workspace),
        "dynamic_workflows_gray": True,
        "summary": {
            "hit_rate": round(hit_rate, 3),
            "max_latency_ms": round(max_latency_ms, 2),
            "case_count": case_count,
        },
        "checks": checks,
        "cases": results,
    }

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _accepted_capabilities(case: dict[str, Any]) -> set[str]:
    accepted = case.get("accept_capabilities")
    if isinstance(accepted, list) and accepted:
        return {str(item) for item in accepted}
    expect = str(case.get("expect_capability") or "").strip()
    return {expect} if expect else set()


def _prepare_dynamic_ingress_workspace(root: Path) -> Path:
    import tempfile

    workspace = Path(tempfile.mkdtemp(prefix="asteria-dynamic-ingress-"))
    InitCommand(workspace).run()
    validator = SchemaValidator(root / "schemas")
    agent_dir = workspace / ".asteria"
    set_isolated_parallel_write_production_path(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    policy_path = agent_dir / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    agent_loop = dict(policy.get("agent_loop") or {})
    assert agent_loop.get(PRODUCTION_PATH_POLICY_KEY) is True
    assert agent_loop.get("orchestration_dynamic_workflows_gray") is True
    return workspace


if __name__ == "__main__":
    main()
