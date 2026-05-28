from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def runtime_progress_metrics(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    runs_dir = root / ".asteria" / "runs"
    if not runs_dir.exists():
        return _empty_metrics()
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    dispatches = []
    permission_decisions = []
    user_progress_runs = 0
    runtime_native_runs = 0
    store = JsonlStore(validator)
    for run_dir in run_dirs:
        dispatch_path = run_dir / "agent_loop_dispatch.json"
        if dispatch_path.exists():
            dispatches.append(dispatch_path)
        progress_path = run_dir / "user_progress.jsonl"
        if progress_path.exists():
            user_progress_runs += 1
            progress_events = store.read_all(progress_path, "user_progress_event")
            if progress_events:
                runtime_native_runs += 1
        decision_path = run_dir / "capability_decisions.jsonl"
        if decision_path.exists():
            permission_decisions.extend(store.read_all(decision_path, schema_name=None))
    profile_counts: dict[str, int] = {}
    for dispatch_path in dispatches:
        try:
            dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        counts = dispatch.get("profile_counts")
        if not isinstance(counts, dict):
            continue
        for profile_id, count in counts.items():
            profile_counts[str(profile_id)] = profile_counts.get(str(profile_id), 0) + int(count)
    decisions_with_reason = [
        item
        for item in permission_decisions
        if isinstance(item.get("decision"), dict) and item["decision"].get("reason")
    ]
    required_profiles = {"research", "brainstorm", "multi_agent"}
    covered_profiles = required_profiles.intersection(profile_counts)
    run_count = len(run_dirs)
    return {
        "schema_version": "0.1.0",
        "run_count": run_count,
        "profile_coverage": {
            "required": sorted(required_profiles),
            "covered": sorted(covered_profiles),
            "missing": sorted(required_profiles - covered_profiles),
            "profile_counts": profile_counts,
            "coverage_ratio": _ratio(len(covered_profiles), len(required_profiles)),
        },
        "permission_reason_coverage": {
            "decision_count": len(permission_decisions),
            "with_reason": len(decisions_with_reason),
            "coverage_ratio": _ratio(len(decisions_with_reason), len(permission_decisions)),
        },
        "runtime_native_progress_coverage": {
            "run_count": run_count,
            "runs_with_user_progress_file": user_progress_runs,
            "runs_with_user_progress_events": runtime_native_runs,
            "coverage_ratio": _ratio(runtime_native_runs, run_count),
        },
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "run_count": 0,
        "profile_coverage": {
            "required": ["brainstorm", "multi_agent", "research"],
            "covered": [],
            "missing": ["brainstorm", "multi_agent", "research"],
            "profile_counts": {},
            "coverage_ratio": 0.0,
        },
        "permission_reason_coverage": {
            "decision_count": 0,
            "with_reason": 0,
            "coverage_ratio": 0.0,
        },
        "runtime_native_progress_coverage": {
            "run_count": 0,
            "runs_with_user_progress_file": 0,
            "runs_with_user_progress_events": 0,
            "coverage_ratio": 0.0,
        },
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
