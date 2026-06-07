"""Orchestration spawn decision maintainer pulse — S63-3 golden cases."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from asteria_runtime.core.orchestration_spawn_eval import (
    SPAWN_EVAL_TIER,
    SpawnEvalCase,
    evaluate_spawn_decision,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, ModelClient, TokenUsage
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


class GateFakeSpawnClient(ModelClient):
    def __init__(self, action: str, reason: str) -> None:
        self._action = action
        self._reason = reason
        self.last_tier: str | None = None

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_tier = request.model_tier
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "action": self._action,
                    "reason": self._reason,
                    "confidence": "high",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-spawn-eval",
            raw_response={},
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run spawn decision quality pulse.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use configured real provider (maintainer only; default uses gate fake_action)",
    )
    parser.add_argument("--summary-json", type=Path, default=None, help="Write report JSON")
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "orchestration_spawn_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    validator = SchemaValidator(SCHEMA_DIR)
    model_client = None
    if args.real:
        model_client = create_model_client(None, validator)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    hits = 0

    for case in gate.get("cases") or []:
        started = time.perf_counter()
        eval_case = SpawnEvalCase.from_dict(case)
        if args.real:
            if model_client is None:
                raise SystemExit("real model client unavailable")
            client: ModelClient = model_client
        else:
            client = GateFakeSpawnClient(
                str(case.get("fake_action") or case.get("expect_action") or "tool"),
                str(case.get("fake_reason") or "gate fake"),
            )

        try:
            outcome = evaluate_spawn_decision(eval_case, model_client=client, validator=validator)
            ok = outcome.action == str(case.get("expect_action") or "")
        except Exception as exc:
            outcome = None
            ok = False
            error = str(exc)
        else:
            error = None

        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        if ok:
            hits += 1

        row: dict[str, Any] = {
            "id": case.get("id"),
            "ok": ok,
            "expect_action": case.get("expect_action"),
            "elapsed_ms": round(elapsed_ms, 2),
            "mode": "real" if args.real else "fake",
        }
        if outcome is not None:
            row.update(outcome.to_dict())
        if error:
            row["error"] = error
        if isinstance(client, GateFakeSpawnClient):
            row["model_tier"] = client.last_tier
        results.append(row)

    case_count = max(len(results), 1)
    hit_rate = hits / case_count
    max_latency_ms = max(latencies) if latencies else 0.0
    thresholds = _thresholds(gate, args.real)
    checks = {
        "hit_rate": hit_rate >= float(thresholds.get("min_hit_rate", 1.0)),
        "latency": max_latency_ms
        <= float(
            thresholds.get("max_inprocess_latency_ms")
            or thresholds.get("max_per_case_latency_ms")
            or 500
        ),
    }
    ok = all(checks.values())

    report = {
        "ok": ok,
        "purpose": gate.get("purpose"),
        "brief": gate.get("brief"),
        "report": gate.get("report"),
        "eval_tier": SPAWN_EVAL_TIER,
        "mode": "real" if args.real else "fake",
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


def _thresholds(gate: dict[str, Any], real: bool) -> dict[str, Any]:
    if real:
        return dict(gate.get("real_thresholds") or {})
    return dict(gate.get("thresholds") or {})


if __name__ == "__main__":
    main()
