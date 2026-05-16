"""Shared helpers for Runtime OS gate evaluation in report commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.acceptance.runtime_os_gate import RuntimeOSGateEvaluator


def runtime_os_full_summary(
    report: dict[str, Any],
    scenarios: list[dict[str, Any]],
    evidence: dict[str, Any],
    *,
    required: bool = False,
) -> dict[str, Any]:
    """Evaluate the Runtime OS gate and combine with release evidence.

    Returns a dict with keys: status, gate, evidence, release_ready.
    Status values: "pass", "fail", "partial", "missing_acceptance".
    """
    gate = RuntimeOSGateEvaluator().evaluate(report, scenarios, required=required).to_dict()
    if not scenarios:
        status = "missing_acceptance"
    elif gate["status"] == "pass" and not evidence.get("worker_results"):
        status = "partial"
    else:
        status = gate["status"]
    return {
        "status": status,
        "gate": gate,
        "evidence": evidence,
        "release_ready": gate["status"] == "pass" and bool(evidence.get("worker_results")),
    }


def runtime_os_release_evidence(
    run_dirs: list[Path],
    read_jsonl: Any,
) -> dict[str, Any]:
    """Collect Runtime OS release evidence from run directories.

    Args:
        run_dirs: List of run directory paths under .agent/runs/.
        read_jsonl: Callable(path, schema_name) -> list[dict].
    """
    summary: dict[str, Any] = {
        "runs_with_workers": 0,
        "worker_invocations": 0,
        "worker_results": 0,
        "failed_worker_results": 0,
        "runtime_profiles": 0,
        "context_mounts": 0,
        "validation_results": 0,
        "task_execution_evidence": 0,
        "task_graph_selections": 0,
    }
    for run_dir in run_dirs:
        workers = read_jsonl(run_dir / "workers.jsonl", "worker_invocation")
        worker_results = read_jsonl(run_dir / "worker_results.jsonl", "worker_result")
        if workers or worker_results:
            summary["runs_with_workers"] += 1
        summary["worker_invocations"] += len(workers)
        summary["worker_results"] += len(worker_results)
        summary["failed_worker_results"] += len(
            [item for item in worker_results if item.get("status") != "succeeded"]
        )
        summary["runtime_profiles"] += len(
            read_jsonl(run_dir / "runtime_profiles.jsonl", "runtime_profile")
        )
        summary["context_mounts"] += len(
            read_jsonl(run_dir / "context_mounts.jsonl", "context_mount")
        )
        summary["validation_results"] += len(
            read_jsonl(run_dir / "validation_results.jsonl", "validation_result")
        )
        summary["task_execution_evidence"] += len(
            read_jsonl(run_dir / "task_execution_evidence.jsonl", "task_execution_evidence")
        )
        events = read_jsonl(run_dir / "events.jsonl", "event")
        summary["task_graph_selections"] += len(
            [item for item in events if item.get("type") == "task_graph_selection"]
        )
    return summary