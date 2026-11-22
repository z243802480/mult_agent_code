"""Bounded execution facts for model feedback, independent of stdout and transport."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asteria_runtime.core.agent_harness import ToolObservation


def _strings(value: Any, limit: int, chars: int) -> dict | None:
    if not isinstance(value, list):
        return None
    prefix = [item for item in value[:limit] if isinstance(item, str)]
    return {"items": [item[:chars] for item in prefix], "omitted_items": len(value) - len(prefix),
            "truncated_items": sum(len(item) > chars for item in prefix)}


def observation_receipt(obs: ToolObservation) -> dict:
    data = obs.data
    receipt = {key: data[key] for key in ("tool_call_id", "verification_ref", "returncode", "verification_method")
               if key in data}
    if obs.dispatch_state != "unknown":
        receipt["dispatch_state"] = obs.dispatch_state
    if not any(key in data for key in ("workspace_scan", "workspace_scan_coverage", "workspace_changes")):
        return receipt  # Legacy records do not establish a scan or effect-free execution.

    facts: dict[str, Any] = {"source": "reported_workspace_scan", "authorization": "not_granted_by_observation"}
    scan = data.get("workspace_scan")
    facts["scan"] = scan[:80] if isinstance(scan, str) else None
    coverage = data.get("workspace_scan_coverage")
    facts["coverage"] = None
    if isinstance(coverage, dict):
        projected: dict[str, Any] = {}
        mechanism = coverage.get("mechanism")
        if isinstance(mechanism, str):
            projected["mechanism"] = mechanism[:80]
        if type(coverage.get("max_scan_files")) is int:
            projected["max_scan_files"] = coverage["max_scan_files"]
        if type(coverage.get("exclusions_grant_permission")) is bool:
            projected["exclusions_grant_permission"] = coverage["exclusions_grant_permission"]
        for key, limit, chars in (("excluded_directories", 16, 80), ("excluded_suffixes", 8, 40),
                                  ("limitations", 4, 180)):
            if key in coverage:
                projected[key] = _strings(coverage[key], limit, chars)
        facts["coverage"] = projected
    changes = data.get("workspace_changes")
    facts["changes"] = ({operation: _strings(changes[operation], 8, 160)
                         for operation in ("created", "modified", "deleted") if operation in changes}
                        if isinstance(changes, dict) else None)
    receipt["workspace_observation"] = facts
    return receipt
