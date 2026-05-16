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
    has_worker_evidence = bool(
        evidence.get("worker_results")
        or evidence.get("acceptance_worker_results_jsonl")
        or evidence.get("workers_jsonl")
    )
    if not scenarios:
        status = "missing_acceptance"
    elif gate["status"] == "pass" and not has_worker_evidence:
        status = "partial"
    else:
        status = gate["status"]
    return {
        "status": status,
        "gate": gate,
        "evidence": evidence,
        "release_ready": gate["status"] == "pass" and has_worker_evidence,
    }


def runtime_os_acceptance_evidence(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize Runtime OS evidence embedded in acceptance scenario results."""
    evidence_keys = [
        "workers_jsonl",
        "worker_results_jsonl",
        "runtime_profiles_jsonl",
        "context_mounts_jsonl",
        "validation_results_jsonl",
        "task_execution_evidence_jsonl",
        "runtime_request_created",
        "merge_gate_blocked",
        "resume_recovered",
        "context_package_sliced",
        "sandbox_backend_recorded",
        "capability_feedback_recorded",
        "debug_consumed_runtime_evidence",
        "review_consumed_runtime_evidence",
    ]
    summary: dict[str, Any] = {
        "acceptance_runtime_os_scenarios": 0,
    }
    for key in evidence_keys:
        summary[f"acceptance_{key}"] = False

    for scenario in scenarios:
        if not scenario.get("ok"):
            continue
        runtime = scenario.get("summary")
        runtime = runtime if isinstance(runtime, dict) else {}
        runtime_os = runtime.get("runtime_os")
        runtime_os = runtime_os if isinstance(runtime_os, dict) else {}
        scenario_evidence = runtime_os.get("evidence")
        scenario_evidence = scenario_evidence if isinstance(scenario_evidence, dict) else {}
        if not scenario_evidence:
            continue
        summary["acceptance_runtime_os_scenarios"] += 1
        for key in evidence_keys:
            if scenario_evidence.get(key):
                summary[f"acceptance_{key}"] = True
    return summary


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
