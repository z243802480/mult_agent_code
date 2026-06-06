from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_tool_surface import tool_surface_contract


MATRIX_CATALOG_PATH = Path("benchmarks") / "runtime_validation_matrix.json"


def runtime_validation_matrix(root: Path, progress_metrics: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog(root)
    raw_cases = catalog.get("cases")
    required_cases = raw_cases if isinstance(raw_cases, list) else []
    evaluated = [
        _evaluate_case(root, case, progress_metrics)
        for case in required_cases
        if isinstance(case, dict)
    ]
    passed = len([case for case in evaluated if case["ok"]])
    implementation_missing = len(
        [case for case in evaluated if case.get("gap_type") == "implementation_missing"]
    )
    evidence_missing = len(
        [case for case in evaluated if case.get("gap_type") == "evidence_missing"]
    )
    historical_noise = len(
        [case for case in evaluated if case.get("gap_type") == "historical_evidence_noise"]
    )
    return {
        "schema_version": "0.1.0",
        "catalog_path": str((root / MATRIX_CATALOG_PATH).resolve()),
        "case_count": len(evaluated),
        "passed": passed,
        "failed": len(evaluated) - passed,
        "ready": bool(evaluated) and passed == len(evaluated),
        "minimum_ready_ratio": float(catalog.get("minimum_ready_ratio") or 1.0),
        "coverage_ratio": _ratio(passed, len(evaluated)),
        "gap_summary": {
            "implementation_missing": implementation_missing,
            "evidence_missing": evidence_missing,
            "historical_evidence_noise": historical_noise,
        },
        "cases": evaluated,
    }


def runtime_validation_matrix_text_lines(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return []
    return [
        "Runtime validation matrix: "
        f"{matrix.get('passed', 0)}/{matrix.get('case_count', 0)} covered "
        f"ready={matrix.get('ready', False)}"
    ]


def _load_catalog(root: Path) -> dict[str, Any]:
    path = root / MATRIX_CATALOG_PATH
    if not path.exists():
        path = Path.cwd() / MATRIX_CATALOG_PATH
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
        gap_type = "none" if ok else "implementation_missing"
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
        gap_type = "none" if ok else "evidence_missing"
    elif evidence == "mcp_invocation":
        adapters = progress_metrics.get("adapter_invocation_coverage") or {}
        ok = int(adapters.get("mcp_invocation_count") or 0) > 0 and int(
            adapters.get("mcp_with_reason") or 0
        ) > 0
        details = {
            "mcp_invocation_count": adapters.get("mcp_invocation_count", 0),
            "mcp_with_reason": adapters.get("mcp_with_reason", 0),
        }
        gap_type = "none" if ok else "evidence_missing"
    elif evidence.startswith("profile:"):
        profile_id = evidence.split(":", 1)[1]
        profile = progress_metrics.get("profile_coverage") or {}
        raw_counts = profile.get("profile_counts") if isinstance(profile, dict) else {}
        counts = raw_counts if isinstance(raw_counts, dict) else {}
        ok = int(counts.get(profile_id) or 0) > 0
        details = {"profile_id": profile_id, "count": int(counts.get(profile_id) or 0)}
        gap_type = "none" if ok else "evidence_missing"
    elif evidence == "permission_reason":
        permission = progress_metrics.get("permission_reason_coverage") or {}
        ok = float(permission.get("coverage_ratio") or 0) >= 1.0 and int(
            permission.get("decision_count") or 0
        ) > 0
        details = {
            "decision_count": permission.get("decision_count", 0),
            "coverage_ratio": permission.get("coverage_ratio", 0),
        }
        gap_type = "none" if ok else "evidence_missing"
    elif evidence == "runtime_native_progress":
        progress = progress_metrics.get("runtime_native_progress_coverage") or {}
        matrix_runs = int(progress.get("matrix_evidence_runs") or 0)
        matrix_ratio = float(progress.get("matrix_evidence_coverage_ratio") or 0)
        ok = (
            matrix_runs > 0
            and matrix_ratio >= 1.0
        ) or (
            float(progress.get("coverage_ratio") or 0) >= 1.0
            and int(progress.get("run_count") or 0) > 0
        )
        details = {
            "run_count": progress.get("run_count", 0),
            "coverage_ratio": progress.get("coverage_ratio", 0),
            "matrix_evidence_runs": matrix_runs,
            "matrix_evidence_coverage_ratio": matrix_ratio,
        }
        gap_type = "none" if ok else "historical_evidence_noise"
    elif evidence == "swarm_scenario_audit":
        from asteria_runtime.core.swarm_scenario_audit import SwarmScenarioAuditor
        from asteria_runtime.storage.schema_validator import SchemaValidator

        validator = SchemaValidator(root / "schemas")
        auditor = SwarmScenarioAuditor(validator)
        passed = 0
        scanned = 0
        runs_root = root / ".asteria" / "runs"
        if runs_root.is_dir():
            for run_dir in sorted(runs_root.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                scanned += 1
                if auditor.evaluate_run_dir(run_dir).ok:
                    passed += 1
                    break
        ok = passed > 0
        details = {"scanned_runs": scanned, "passed_runs": passed}
        gap_type = "none" if ok else "evidence_missing"
    elif evidence == "production_gray_band":
        from asteria_runtime.core.swarm_production_gray import find_production_gray_evidence

        payload = find_production_gray_evidence(root)
        ok = isinstance(payload, dict) and bool(payload.get("ok"))
        details = {
            "case_id": (payload or {}).get("case_id"),
            "run_id": (payload or {}).get("run_id"),
            "execute_parallel_disjoint": (payload or {}).get("execute_parallel_disjoint"),
        }
        gap_type = "none" if ok else "evidence_missing"
    else:
        details = {"unknown_evidence": evidence, "root": str(root)}
        gap_type = "implementation_missing"
    return {
        "id": str(case.get("id") or evidence or "unknown"),
        "priority": str(case.get("priority") or "P1"),
        "evidence": evidence,
        "ok": ok,
        "gap_type": gap_type,
        "details": details,
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
