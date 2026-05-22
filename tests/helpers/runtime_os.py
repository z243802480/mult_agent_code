from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.acceptance.runtime_os_catalog import RUNTIME_OS_CAPABILITIES


def runtime_os_capability_count() -> int:
    return len(RUNTIME_OS_CAPABILITIES)


def runtime_os_pass_scenarios() -> list[dict[str, Any]]:
    return [_runtime_os_scenario(capability) for capability in RUNTIME_OS_CAPABILITIES]


def runtime_os_pass_report(
    root: Path,
    *,
    suite: str = "core",
    created_at: str = "2026-05-13T10:00:00+08:00",
) -> dict[str, Any]:
    scenarios = runtime_os_pass_scenarios()
    return {
        "schema_version": "0.1.0",
        "suite": suite,
        "requested_scenarios": [],
        "root": str(root),
        "ok": True,
        "returncode": 0,
        "created_at": created_at,
        "summary_json": str(root / ".asteria" / "acceptance" / "latest_summary.json"),
        "aggregate": {"total": len(scenarios), "passed": len(scenarios), "failed": 0},
        "trend_warnings": [],
        "scenarios": scenarios,
        "scenario_metadata": [
            {
                "scenario": item["scenario"],
                "capability": item["capability"],
                "tier": item["tier"],
                "kind": "runtime_os",
            }
            for item in scenarios
        ],
    }


def _runtime_os_scenario(capability: Any) -> dict[str, Any]:
    evidence = {
        key: True
        for key in (
            *capability.required_evidence,
            *capability.suite_evidence,
            *capability.special_evidence,
        )
    }
    return {
        "scenario": capability.scenario,
        "capability": capability.capability,
        "tier": capability.tier,
        "ok": True,
        "workspace": None,
        "failure_summary": "",
        "stdout_tail": "",
        "stderr_tail": "",
        "summary": {
            "runtime_os": {
                "capability": capability.capability,
                "evidence": evidence,
            }
        },
    }
