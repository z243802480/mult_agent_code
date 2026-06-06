from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from asteria_runtime.core.north_star import NorthStarStore


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def evaluate_stability_window(
    window: dict[str, Any],
    *,
    repo_root: Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Evaluate the Phase 2 stability observation window for North Star RFC entry."""

    root = _repo_root(repo_root)
    current = today or date.today()
    window_start = _parse_date(str(window.get("window_start") or current.isoformat()))
    window_days = int(window.get("window_days") or 14)
    opens_on = _parse_date(str(window.get("opens_on") or (window_start + timedelta(days=window_days)).isoformat()))
    days_elapsed = max(0, (current - window_start).days)
    days_remaining = max(0, (opens_on - current).days)

    missing_signoffs = [
        str(path)
        for path in window.get("required_signoffs") or []
        if not (root / str(path)).exists()
    ]
    missing_manifests = [
        str(path)
        for path in window.get("required_gate_manifests") or []
        if not (root / str(path)).exists()
    ]
    missing_rfc = [
        str(path)
        for path in [window.get("north_star_rfc"), window.get("north_star_schema")]
        if path and not (root / str(path)).exists()
    ]
    prerequisites_ok = not missing_signoffs and not missing_manifests and not missing_rfc

    if not prerequisites_ok:
        status = "blocked"
        summary = "Stability window prerequisites are incomplete."
    elif current < opens_on:
        status = "observing"
        summary = (
            f"Phase 2 stability observation in progress; "
            f"{days_remaining} day(s) remain before North Star RFC implementation may start."
        )
    else:
        status = "ready_for_implementation"
        summary = (
            "Phase 2 stability window complete; North Star v1 implementation may start per RFC."
        )

    return {
        "schema_version": "0.1.0",
        "status": status,
        "summary": summary,
        "window_start": window_start.isoformat(),
        "opens_on": opens_on.isoformat(),
        "window_days": window_days,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "prerequisites_ok": prerequisites_ok,
        "missing_signoffs": missing_signoffs,
        "missing_gate_manifests": missing_manifests,
        "missing_rfc_artifacts": missing_rfc,
        "north_star_rfc": window.get("north_star_rfc"),
        "next_slice_brief": window.get("next_slice_brief"),
        "contract_tests": list(window.get("contract_tests") or []),
        "ready_for_implementation": status == "ready_for_implementation",
    }


def long_horizon_projection(workspace_root: Path | None = None, *, today: date | None = None) -> dict[str, Any]:
    workspace = (workspace_root or Path.cwd()).resolve()
    manifest_root = _repo_root(workspace)
    window = load_stability_window(manifest_root)
    if not window:
        return {
            "status": "unavailable",
            "summary": "Long-horizon readiness manifest is unavailable.",
            "north_star_configured": False,
            "ready_for_implementation": False,
        }
    audit = evaluate_stability_window(window, repo_root=manifest_root, today=today)
    store = NorthStarStore(workspace, validator=None)
    north_star_configured = store.exists()
    status = audit["status"]
    summary_payload = store.summary_for_status()
    if north_star_configured and summary_payload:
        user_status = "configured"
        summary = (
            f"Long-horizon goal: {summary_payload.get('title')}. "
            f"Active milestone: {summary_payload.get('active_milestone') or 'none'}."
        )
    elif status == "ready_for_implementation" and not north_star_configured:
        user_status = "ready_not_configured"
        summary = "Long-horizon goals may now be configured; no north star file exists yet."
    else:
        user_status = status
        summary = audit["summary"]
    payload: dict[str, Any] = {
        "status": user_status,
        "summary": summary,
        "opens_on": audit["opens_on"],
        "days_remaining": audit["days_remaining"],
        "ready_for_implementation": audit["ready_for_implementation"],
        "north_star_configured": north_star_configured,
        "rfc_path": audit.get("north_star_rfc"),
    }
    if summary_payload:
        payload["north_star"] = summary_payload
    from asteria_runtime.core.long_horizon_completion import latest_slice_completion_eval

    last_eval = latest_slice_completion_eval(workspace)
    if last_eval:
        payload["last_slice_completion"] = {
            "run_id": last_eval.get("run_id"),
            "slice_complete": last_eval.get("slice_complete"),
            "summary": last_eval.get("summary"),
        }
    return payload


def _repo_root(start: Path | None = None) -> Path:
    probe = (start or Path.cwd()).resolve()
    for candidate in [probe, *probe.parents]:
        if (candidate / "benchmarks" / "phase2_stability_window.json").exists():
            return candidate
    return Path.cwd()


def load_stability_window(repo_root: Path | None = None) -> dict[str, Any]:
    root = _repo_root(repo_root)
    path = root / "benchmarks" / "phase2_stability_window.json"
    return _read_json(path)
