from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _repair_attempts_from_task_plan(task_plan: dict[str, Any]) -> int:
    count = 0
    for task in task_plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        replan = task.get("replan")
        if isinstance(replan, dict) and replan.get("source_task_id"):
            count += 1
    return count


def sample_run_stability(run_dir: Path) -> dict[str, Any]:
    """Extract stability metrics from one run directory."""

    run = _read_json(run_dir / "run.json")
    workspace_envelope = _read_json(run_dir / "workspace_envelope.json")
    cost_report = _read_json(run_dir / "cost_report.json")
    task_plan = _read_json(run_dir / "task_plan.json")
    model_calls_path = run_dir / "model_calls.jsonl"
    model_call_count = 0
    if model_calls_path.exists():
        model_call_count = len(
            [line for line in model_calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        )
    model_calls = int(cost_report.get("model_calls") or model_call_count or 0)
    repair_attempts = int(cost_report.get("repair_attempts") or 0)
    if repair_attempts == 0:
        repair_attempts = _repair_attempts_from_task_plan(task_plan)
    permission_mode = str(
        workspace_envelope.get("permission_mode")
        or (run.get("permission_policy") or {}).get("mode")
        or run.get("permission_mode")
        or "unknown"
    )
    return {
        "run_id": str(run.get("run_id") or run_dir.name),
        "permission_mode": permission_mode,
        "model_calls": model_calls,
        "repair_attempts": repair_attempts,
        "cost_status": cost_report.get("status"),
        "run_status": run.get("status"),
    }


def sample_matrix_case(case: dict[str, Any]) -> dict[str, Any] | None:
    diagnostics = case.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return {
        "run_id": str(case.get("name") or case.get("case_id") or "matrix-case"),
        "permission_mode": "reviewed_auto",
        "model_calls": int(diagnostics.get("model_calls") or 0),
        "repair_attempts": int(diagnostics.get("repair_attempts") or 0),
        "cost_status": diagnostics.get("cost_status"),
        "run_status": diagnostics.get("run_status"),
        "source": "matrix_summary",
    }


def load_matrix_summary_samples(path: Path) -> list[dict[str, Any]]:
    summary = _read_json(path)
    samples: list[dict[str, Any]] = []
    for case in summary.get("cases") or []:
        if not isinstance(case, dict):
            continue
        sample = sample_matrix_case(case)
        if sample is not None:
            samples.append(sample)
    return samples


def evaluate_stability_samples(
    samples: list[dict[str, Any]],
    *,
    permission_mode: str = "reviewed_auto",
    median_model_calls_max: int = 5,
    max_repair_attempts_per_run: int = 1,
) -> dict[str, Any]:
    scoped = [
        sample
        for sample in samples
        if str(sample.get("permission_mode") or "") == permission_mode
    ]
    if not scoped:
        return {
            "status": "fail",
            "ok": False,
            "reason": f"no samples for permission_mode={permission_mode}",
            "sample_count": 0,
            "permission_mode": permission_mode,
            "thresholds": {
                "median_model_calls_max": median_model_calls_max,
                "max_repair_attempts_per_run": max_repair_attempts_per_run,
            },
            "metrics": {},
            "violations": [],
            "samples": samples,
        }

    model_calls = [int(sample.get("model_calls") or 0) for sample in scoped]
    repair_attempts = [int(sample.get("repair_attempts") or 0) for sample in scoped]
    median_model_calls = statistics.median(model_calls)
    max_repair = max(repair_attempts) if repair_attempts else 0
    violations: list[str] = []
    if median_model_calls > median_model_calls_max:
        violations.append(
            f"median model_calls {median_model_calls} exceeds {median_model_calls_max}"
        )
    if max_repair > max_repair_attempts_per_run:
        violations.append(
            f"max repair_attempts {max_repair} exceeds {max_repair_attempts_per_run}"
        )
    ok = not violations
    return {
        "status": "pass" if ok else "fail",
        "ok": ok,
        "reason": "within thresholds" if ok else "; ".join(violations),
        "sample_count": len(scoped),
        "permission_mode": permission_mode,
        "thresholds": {
            "median_model_calls_max": median_model_calls_max,
            "max_repair_attempts_per_run": max_repair_attempts_per_run,
        },
        "metrics": {
            "median_model_calls": median_model_calls,
            "max_repair_attempts": max_repair,
            "model_calls": model_calls,
            "repair_attempts": repair_attempts,
        },
        "violations": violations,
        "samples": scoped,
    }


def evaluate_stability_gate(gate: dict[str, Any], *, run_dirs: list[Path]) -> dict[str, Any]:
    thresholds = gate.get("thresholds") or {}
    permission_mode = str(gate.get("permission_mode") or "reviewed_auto")
    samples = [sample_run_stability(run_dir) for run_dir in run_dirs]
    for evidence in gate.get("real_provider_evidence") or []:
        if not isinstance(evidence, str) or not evidence.endswith("matrix_summary.json"):
            continue
        path = Path(evidence)
        if path.exists():
            samples.extend(load_matrix_summary_samples(path))
    return evaluate_stability_samples(
        samples,
        permission_mode=permission_mode,
        median_model_calls_max=int(thresholds.get("median_model_calls_max") or 5),
        max_repair_attempts_per_run=int(thresholds.get("max_repair_attempts_per_run") or 1),
    )
