"""Orchestration route maintainer pulse — rules CI + optional real-model eval (S62-4)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.route_worker import handle_route_request


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run orchestration route quality pulse.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run strong model route cases (S62-4 maintainer eval)",
    )
    parser.add_argument("--summary-json", type=Path, default=None, help="Write report JSON")
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "orchestration_route_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    workspace = _prepare_workspace(root)

    mode = "model" if args.real else "rules"
    cases = [
        case
        for case in (gate.get("cases") or [])
        if str(case.get("router_mode") or "rules") == mode
    ]
    if not cases:
        raise SystemExit(f"no cases for router_mode={mode}")

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
            "rules_only": mode == "rules",
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
    thresholds = _thresholds(gate, args.real)

    checks = {
        "hit_rate": hit_rate >= float(thresholds.get("min_hit_rate", 1.0)),
        "latency": max_latency_ms <= float(
            thresholds.get("max_inprocess_latency_ms")
            or thresholds.get("max_per_case_latency_ms")
            or 250
        ),
    }
    ok = all(checks.values())

    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "brief": gate.get("brief"),
        "mode": mode,
        "production_router": "model (strong semantic)",
        "workspace": str(workspace),
        "summary": {
            "hit_rate": round(hit_rate, 3),
            "max_latency_ms": round(max_latency_ms, 2),
            "case_count": case_count,
        },
        "checks": checks,
        "cases": results,
    }
    if args.real:
        report["eval_tier"] = "strong"
    else:
        report["pulse_router"] = "rules (maintainer/CI only)"

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


def _thresholds(gate: dict[str, Any], real: bool) -> dict[str, Any]:
    if real:
        return dict(gate.get("real_thresholds") or {})
    return dict(gate.get("thresholds") or {})


def _prepare_workspace(root: Path) -> Path:
    import tempfile

    workspace = Path(tempfile.mkdtemp(prefix="asteria-route-pulse-"))
    InitCommand(workspace).run()
    return workspace


if __name__ == "__main__":
    main()
