from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_tool_surface import tool_surface_contract


MATRIX_CATALOG_PATH = Path("benchmarks") / "runtime_gray_matrix.json"


def runtime_gray_matrix(root: Path, progress_metrics: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog(root)
    raw_cases = catalog.get("cases")
    required_cases = raw_cases if isinstance(raw_cases, list) else []
    evaluated = [
        _evaluate_case(root, case, progress_metrics)
        for case in required_cases
        if isinstance(case, dict)
    ]
    passed = len([case for case in evaluated if case["ok"]])
    return {
        "schema_version": "0.1.0",
        "catalog_path": str((root / MATRIX_CATALOG_PATH).resolve()),
        "case_count": len(evaluated),
        "passed": passed,
        "failed": len(evaluated) - passed,
        "ready": bool(evaluated) and passed == len(evaluated),
        "minimum_ready_ratio": float(catalog.get("minimum_ready_ratio") or 1.0),
        "coverage_ratio": _ratio(passed, len(evaluated)),
        "cases": evaluated,
    }


def runtime_gray_matrix_text_lines(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return []
    return [
        "Runtime gray matrix: "
        f"{matrix.get('passed', 0)}/{matrix.get('case_count', 0)} covered "
        f"ready={matrix.get('ready', False)}"
    ]


def _load_catalog(root: Path) -> dict[str, Any]:
    path = root / MATRIX_CATALOG_PATH
    if not path.exists():
        return _default_catalog()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_catalog()
    return data if isinstance(data, dict) else _default_catalog()


def _default_catalog() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "minimum_ready_ratio": 1.0,
        "cases": [
            {"id": "model_tool_surface", "evidence": "model_tool_surface_contract"},
            {"id": "skill_adapter", "evidence": "skill_invocation"},
            {"id": "mcp_adapter", "evidence": "mcp_invocation"},
            {"id": "profile_research", "evidence": "profile:research"},
            {"id": "profile_brainstorm", "evidence": "profile:brainstorm"},
            {"id": "profile_multi_agent", "evidence": "profile:multi_agent"},
            {"id": "permission_reason", "evidence": "permission_reason"},
            {"id": "runtime_progress", "evidence": "runtime_native_progress"},
        ],
    }


def _evaluate_case(
    root: Path,
    case: dict[str, Any],
    progress_metrics: dict[str, Any],
) -> dict[str, Any]:
    evidence = str(case.get("evidence") or "")
    ok = False
    details: dict[str, Any] = {}
    if evidence == "model_tool_surface_contract":
        contract = tool_surface_contract(
            [
                "find_files",
                "read_file",
                "list_files",
                "search_text",
                "write_file",
                "apply_patch",
                "run_command",
                "run_tests",
                "todo_read",
                "todo_write",
            ],
            allow_shell=True,
        )
        surface = contract.get("model_facing_standard_surface")
        surface = surface if isinstance(surface, dict) else {}
        ok = surface.get("status") == "ready"
        details = {
            "status": surface.get("status"),
            "model_tool_count": len(surface.get("tools") or []),
        }
    elif evidence == "skill_invocation":
        adapters = progress_metrics.get("adapter_invocation_coverage") or {}
        ok = int(adapters.get("skill_invocation_count") or 0) > 0 and int(
            adapters.get("skill_with_reason") or 0
        ) > 0
        details = {
            "skill_invocation_count": adapters.get("skill_invocation_count", 0),
            "skill_with_reason": adapters.get("skill_with_reason", 0),
        }
    elif evidence == "mcp_invocation":
        adapters = progress_metrics.get("adapter_invocation_coverage") or {}
        ok = int(adapters.get("mcp_invocation_count") or 0) > 0 and int(
            adapters.get("mcp_with_reason") or 0
        ) > 0
        details = {
            "mcp_invocation_count": adapters.get("mcp_invocation_count", 0),
            "mcp_with_reason": adapters.get("mcp_with_reason", 0),
        }
    elif evidence.startswith("profile:"):
        profile_id = evidence.split(":", 1)[1]
        profile = progress_metrics.get("profile_coverage") or {}
        raw_counts = profile.get("profile_counts") if isinstance(profile, dict) else {}
        counts = raw_counts if isinstance(raw_counts, dict) else {}
        ok = int(counts.get(profile_id) or 0) > 0
        details = {"profile_id": profile_id, "count": int(counts.get(profile_id) or 0)}
    elif evidence == "permission_reason":
        permission = progress_metrics.get("permission_reason_coverage") or {}
        ok = float(permission.get("coverage_ratio") or 0) >= 1.0 and int(
            permission.get("decision_count") or 0
        ) > 0
        details = {
            "decision_count": permission.get("decision_count", 0),
            "coverage_ratio": permission.get("coverage_ratio", 0),
        }
    elif evidence == "runtime_native_progress":
        progress = progress_metrics.get("runtime_native_progress_coverage") or {}
        ok = float(progress.get("coverage_ratio") or 0) >= 1.0 and int(
            progress.get("run_count") or 0
        ) > 0
        details = {
            "run_count": progress.get("run_count", 0),
            "coverage_ratio": progress.get("coverage_ratio", 0),
        }
    else:
        details = {"unknown_evidence": evidence, "root": str(root)}
    return {
        "id": str(case.get("id") or evidence or "unknown"),
        "priority": str(case.get("priority") or "P1"),
        "evidence": evidence,
        "ok": ok,
        "details": details,
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
