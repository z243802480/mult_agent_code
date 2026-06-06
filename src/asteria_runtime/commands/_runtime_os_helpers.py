"""Shared helpers for Runtime OS gate evaluation in report commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.acceptance.runtime_os_gate import RuntimeOSGateEvaluator
from asteria_runtime.acceptance.runtime_os_catalog import RUNTIME_OS_CAPABILITIES
from asteria_runtime.core.capability_manifest_catalog import capability_manifest_catalog_audit
from asteria_runtime.core.prompt_envelope import capability_manifest_hash, cache_break_reasons


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
    evidence_keys = runtime_os_evidence_keys()
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
        run_dirs: List of run directory paths under .asteria/runs/.
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
        "candidate_promotions": 0,
        "candidate_promotions_pending": 0,
        "candidate_promotions_blocked": 0,
        "candidate_promotions_promoted": 0,
        "capability_manifest_audit": {
            "prompt_envelopes": 0,
            "context_envelopes": 0,
            "model_calls_with_prompt_envelope": 0,
            "model_calls_with_context_envelope": 0,
            "model_calls_with_capability_manifest": 0,
            "manifest_hashes": [],
            "context_envelope_hashes": [],
            "manifest_changed": False,
            "cache_break_reasons": [],
            "model_metadata_complete": False,
            "context_envelope_metadata_complete": False,
            "catalog_aligned": True,
            "catalog_audit_status": "skipped",
            "catalog_mismatches": [],
            "audit_chain": "manifest/context_envelope -> cache_break_reasons -> model_call_metadata",
        },
    }
    manifest_audit = _empty_manifest_audit()
    catalog_audits: list[dict[str, Any]] = []
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
        promotions = _latest_promotions(
            read_jsonl(run_dir / "candidate_promotions.jsonl", "candidate_promotion")
        )
        summary["candidate_promotions"] += len(promotions)
        summary["candidate_promotions_pending"] += len(
            [
                item
                for item in promotions
                if item.get("status") in {"queued", "pending_manual_approval", "approved"}
            ]
        )
        summary["candidate_promotions_blocked"] += len(
            [item for item in promotions if item.get("status") in {"blocked", "promotion_failed"}]
        )
        summary["candidate_promotions_promoted"] += len(
            [item for item in promotions if item.get("status") == "promoted"]
        )
        _merge_manifest_audit(manifest_audit, _capability_manifest_audit(run_dir, read_jsonl))
        catalog_audits.append(capability_manifest_catalog_audit(run_dir))
    manifest_hashes = sorted(manifest_audit["manifest_hashes"])
    catalog_mismatches = [
        mismatch
        for audit in catalog_audits
        for mismatch in (audit.get("mismatches") or [])
    ]
    catalog_statuses = {str(audit.get("status") or "skipped") for audit in catalog_audits}
    summary["capability_manifest_audit"] = {
        "prompt_envelopes": manifest_audit["prompt_envelopes"],
        "context_envelopes": manifest_audit["context_envelopes"],
        "model_calls_with_prompt_envelope": manifest_audit["model_calls_with_prompt_envelope"],
        "model_calls_with_context_envelope": manifest_audit[
            "model_calls_with_context_envelope"
        ],
        "model_calls_with_capability_manifest": manifest_audit[
            "model_calls_with_capability_manifest"
        ],
        "manifest_hashes": manifest_hashes,
        "context_envelope_hashes": sorted(manifest_audit["context_envelope_hashes"]),
        "manifest_changed": len(manifest_hashes) > 1,
        "cache_break_reasons": sorted(manifest_audit["cache_break_reasons"]),
        "model_metadata_complete": (
            manifest_audit["model_calls_with_prompt_envelope"] > 0
            and manifest_audit["model_calls_with_prompt_envelope"]
            == manifest_audit["model_calls_with_capability_manifest"]
        ),
        "context_envelope_metadata_complete": (
            manifest_audit["context_envelopes"] > 0
            and manifest_audit["model_calls_with_context_envelope"] > 0
        ),
        "catalog_aligned": not catalog_mismatches,
        "catalog_audit_status": (
            "checked"
            if "checked" in catalog_statuses
            else "skipped"
            if catalog_audits
            else "skipped"
        ),
        "catalog_mismatches": catalog_mismatches,
        "audit_chain": "manifest/context_envelope -> cache_break_reasons -> model_call_metadata",
    }
    return summary


def runtime_os_evidence_keys() -> list[str]:
    keys: list[str] = []
    for capability in RUNTIME_OS_CAPABILITIES:
        for key in (
            *capability.required_evidence,
            *capability.suite_evidence,
            *capability.special_evidence,
        ):
            if key not in keys:
                keys.append(key)
    return keys


def runtime_os_catalog_report() -> dict[str, Any]:
    return {
        "capabilities": [
            {
                "scenario": item.scenario,
                "capability": item.capability,
                "tier": item.tier,
                "kind": item.kind,
                "required_evidence": list(item.required_evidence),
                "suite_evidence": list(item.suite_evidence),
                "special_evidence": list(item.special_evidence),
            }
            for item in RUNTIME_OS_CAPABILITIES
        ],
        "evidence_keys": runtime_os_evidence_keys(),
    }


def _latest_promotions(promotions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for promotion in promotions:
        promotion_id = promotion.get("promotion_id")
        if promotion_id:
            latest[str(promotion_id)] = promotion
    return list(latest.values())


def _empty_manifest_audit() -> dict[str, Any]:
    return {
        "prompt_envelopes": 0,
        "context_envelopes": 0,
        "model_calls_with_prompt_envelope": 0,
        "model_calls_with_context_envelope": 0,
        "model_calls_with_capability_manifest": 0,
        "manifest_hashes": set(),
        "context_envelope_hashes": set(),
        "cache_break_reasons": set(),
    }


def _merge_manifest_audit(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["prompt_envelopes"] += int(source.get("prompt_envelopes") or 0)
    target["model_calls_with_prompt_envelope"] += int(
        source.get("model_calls_with_prompt_envelope") or 0
    )
    target["model_calls_with_capability_manifest"] += int(
        source.get("model_calls_with_capability_manifest") or 0
    )
    target["context_envelopes"] += int(source.get("context_envelopes") or 0)
    target["model_calls_with_context_envelope"] += int(
        source.get("model_calls_with_context_envelope") or 0
    )
    target["manifest_hashes"].update(source.get("manifest_hashes") or [])
    target["context_envelope_hashes"].update(source.get("context_envelope_hashes") or [])
    target["cache_break_reasons"].update(source.get("cache_break_reasons") or [])


def _capability_manifest_audit(run_dir: Path, read_jsonl: Any) -> dict[str, Any]:
    audit = _empty_manifest_audit()
    envelope_hashes: set[str] = set()
    context_envelope_hashes: set[str] = set()
    for path in sorted(run_dir.glob("prompt_envelope*.json")):
        try:
            data = _read_json(path)
        except Exception:  # noqa: BLE001
            continue
        manifest = data.get("capability_manifest")
        if isinstance(manifest, dict):
            audit["prompt_envelopes"] += 1
            audit["manifest_hashes"].add(capability_manifest_hash(manifest))
        audit["cache_break_reasons"].update(cache_break_reasons(data))
        content_hash = data.get("content_hash")
        if content_hash:
            envelope_hashes.add(str(content_hash))
    for path in sorted(run_dir.rglob("context_envelope*.json")):
        try:
            data = _read_json(path)
        except Exception:  # noqa: BLE001
            continue
        payload_hash = data.get("payload_hash")
        if payload_hash:
            audit["context_envelopes"] += 1
            context_envelope_hashes.add(str(payload_hash))
            audit["context_envelope_hashes"].add(str(payload_hash))
    for call in read_jsonl(run_dir / "model_calls.jsonl", "model_call"):
        if call.get("prompt_envelope_hash") in envelope_hashes:
            audit["model_calls_with_prompt_envelope"] += 1
        if call.get("context_envelope_hash"):
            audit["context_envelope_hashes"].add(str(call["context_envelope_hash"]))
        if call.get("context_envelope_hash") in context_envelope_hashes:
            audit["model_calls_with_context_envelope"] += 1
        if call.get("capability_manifest_hash"):
            audit["model_calls_with_capability_manifest"] += 1
            audit["manifest_hashes"].add(str(call["capability_manifest_hash"]))
    return audit


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
