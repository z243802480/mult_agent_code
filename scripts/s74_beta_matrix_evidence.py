"""Summarize or explicitly run S74 Beta matrix evidence (S74-C / W1-D).

The default path is evidence-only and never starts a provider or scenario. Pass
``--live`` explicitly to run missing slots. Config: benchmarks/s74_beta_matrix_gate.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_src_path() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_src_path()

from asteria_runtime.acceptance.runtime_os_scenarios import run_runtime_os_scenario  # noqa: E402
from asteria_runtime.core.s74_session_telemetry_audit import (  # noqa: E402
    apply_session_audit_to_unified,
)
from asteria_runtime.real_model_acceptance import (  # noqa: E402
    SCENARIOS,
    build_parser,
    run_scenario,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Collect S74 Beta matrix evidence.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--slot",
        action="append",
        dest="slots",
        help="Run only these slot ids (default: all in gate config)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly run slots without imported evidence, including real providers",
    )
    parser.add_argument(
        "--import-summary",
        type=Path,
        action="append",
        default=[],
        help="Import prior acceptance summary JSON keyed by scenario name",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: .asteria/verification/s74_beta_matrix_YYYYMMDD.json)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    gate_path = root / "benchmarks" / "s74_beta_matrix_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    result_fields: list[str] = list(gate.get("result_fields") or [])
    audit_policy = gate.get("audit_policy") or {}
    imports = _load_imports(args.import_summary)

    selected_ids = set(args.slots) if args.slots else None
    slot_results: list[dict[str, Any]] = []

    for slot in gate.get("beta_matrix_slots") or []:
        slot_id = str(slot.get("id") or "")
        if selected_ids is not None and slot_id not in selected_ids:
            continue
        scenario_name = str(slot.get("scenario") or "")
        imported = imports.get(scenario_name)
        if imported is not None:
            slot_results.append(
                _slot_from_import(
                    slot,
                    imported,
                    result_fields=result_fields,
                    root=root,
                    audit_policy=audit_policy,
                )
            )
            continue
        if not args.live:
            slot_results.append(
                _skipped_slot(
                    slot,
                    reason="no_imported_evidence; pass --live to run",
                    result_fields=result_fields,
                )
            )
            continue
        if scenario_name == "runtime_delegation_contract":
            raw = _run_runtime_os_scenario(root, scenario_name, slot)
        elif scenario_name in SCENARIOS:
            raw = _run_acceptance_scenario(root, scenario_name, slot)
        else:
            slot_results.append(
                _skipped_slot(
                    slot,
                    reason=f"unknown_scenario:{scenario_name}",
                    result_fields=result_fields,
                )
            )
            continue
        slot_results.append(
            _normalize_slot(
                slot,
                raw,
                result_fields=result_fields,
                root=root,
                audit_policy=audit_policy,
            )
        )

    recorded = [item for item in slot_results if item.get("status") == "recorded"]
    complete = bool(slot_results) and len(recorded) == len(slot_results)
    ok = bool(recorded) and all(item.get("unified", {}).get("goal_completed") for item in recorded)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    output = args.output or (
        root / ".asteria" / "verification" / f"s74_beta_matrix_{stamp}.json"
    )
    report = {
        "ok": ok and complete,
        "complete": complete,
        "purpose": "S74 Beta task matrix — unified product evidence (S74-C / W1-D)",
        "gate": str(gate_path.relative_to(root)).replace("\\", "/"),
        "plan": gate.get("plan"),
        "brief": gate.get("brief"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "evidence_only",
        "result_fields": result_fields,
        "audit_policy": audit_policy,
        "slots": slot_results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["evidence_path"] = str(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


def _load_imports(paths: list[Path]) -> dict[str, dict[str, Any]]:
    imports: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "scenarios" in payload:
            for item in payload.get("scenarios") or []:
                name = str(item.get("scenario") or "")
                if name:
                    imports[name] = item
            continue
        scenario = payload.get("scenario")
        if scenario:
            imports[str(scenario)] = payload
            continue
        for item in payload.get("slots") or []:
            name = str(item.get("scenario") or "")
            raw = item.get("raw") or item
            if name:
                imports[name] = raw
    return imports


def _run_runtime_os_scenario(
    root: Path, scenario_name: str, slot: dict[str, Any]
) -> dict[str, Any]:
    del slot
    workspace = root / ".asteria" / "tmp" / f"s74-matrix-{scenario_name}"
    if workspace.exists():
        import shutil

        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    return run_runtime_os_scenario(
        workspace=workspace,
        scenario_name=scenario_name,
        capability="runtime_delegation",
        tier="core",
    )


def _run_acceptance_scenario(
    root: Path, scenario_name: str, slot: dict[str, Any]
) -> dict[str, Any]:
    del slot
    scenario = SCENARIOS[scenario_name]
    workspace = root / ".asteria" / "tmp" / f"s74-matrix-{scenario_name}"
    if workspace.exists():
        import shutil

        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    parser = build_parser()
    timeout = "600" if scenario_name == "validation_subagent_delegation" else "240"
    args = parser.parse_args(
        [
            "--suite",
            "validation",
            "--scenario",
            scenario_name,
            "--root",
            str(root),
            "--summary-json",
            str(workspace / "acceptance_summary.json"),
            "--scenario-timeout-seconds",
            timeout,
        ]
    )
    return run_scenario(args, root, scenario)


def _skipped_slot(slot: dict[str, Any], *, reason: str, result_fields: list[str]) -> dict[str, Any]:
    return {
        "id": slot.get("id"),
        "path": slot.get("path"),
        "scenario": slot.get("scenario"),
        "status": "skipped",
        "skip_reason": reason,
        "unified": {field: None for field in result_fields},
    }


def _slot_from_import(
    slot: dict[str, Any],
    raw: dict[str, Any],
    *,
    result_fields: list[str],
    root: Path,
    audit_policy: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_slot(
        slot,
        raw,
        result_fields=result_fields,
        root=root,
        audit_policy=audit_policy,
    )
    normalized["status"] = "recorded"
    normalized["source"] = "import"
    return normalized


def _normalize_slot(
    slot: dict[str, Any],
    raw: dict[str, Any],
    *,
    result_fields: list[str],
    root: Path | None = None,
    audit_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    diagnostics = summary.get("diagnostics") if isinstance(summary.get("diagnostics"), dict) else {}
    route = raw.get("route_evidence") if isinstance(raw.get("route_evidence"), dict) else {}
    runtime_summary = summary if raw.get("scenario") == "runtime_delegation_contract" else {}
    ok = bool(raw.get("ok"))
    unified: dict[str, Any] = {
        "goal_completed": ok,
        "artifact_verified": _coalesce(
            diagnostics.get("artifact_verified"),
            runtime_summary.get("delegation_evidence_consistent"),
            ok,
        ),
        "accepted_or_blocked_reason": _coalesce(
            diagnostics.get("accepted_or_blocked_reason"),
            summary.get("failure_summary"),
            None if ok else raw.get("stderr") or "scenario_failed",
        ),
        "elapsed_total": _coalesce(
            diagnostics.get("elapsed_total"),
            raw.get("duration_seconds"),
        ),
        "model_calls": _coalesce(
            diagnostics.get("model_calls"),
            route.get("model_call_count") if route.get("available") else None,
        ),
        "tool_calls": diagnostics.get("tool_calls"),
        "repair_count": _coalesce(
            diagnostics.get("repair_attempts"),
            diagnostics.get("repair_count"),
            0,
        ),
        "replan_count": _coalesce(diagnostics.get("replan_count"), 0),
        "user_progress_consistent": diagnostics.get("user_progress_consistent"),
        "studio_runtime_consistent": diagnostics.get("studio_runtime_consistent"),
    }
    for field in result_fields:
        unified.setdefault(field, None)
    delegation = _delegation_metrics(
        raw.get("workspace"),
        summary.get("run_id"),
        scenario=str(slot.get("scenario") or raw.get("scenario") or ""),
    )
    raw_payload: dict[str, Any] = {
        "duration_seconds": raw.get("duration_seconds"),
        "workspace": raw.get("workspace"),
        "route_evidence": raw.get("route_evidence"),
        "summary_keys": sorted(summary.keys()) if summary else [],
    }
    if delegation:
        raw_payload["delegation"] = delegation
        if delegation.get("model_call_count") is not None:
            unified["model_calls"] = delegation["model_call_count"]
        if delegation.get("tool_call_count") is not None:
            unified["tool_calls"] = delegation["tool_call_count"]
    workspace_path, run_id = _resolve_run_context(raw, summary)
    if root is not None and bool(unified.get("goal_completed")):
        apply_session_audit_to_unified(
            unified,
            repo_root=root,
            workspace=workspace_path,
            run_id=run_id,
            policy=audit_policy,
            slot_id=str(slot.get("id") or ""),
        )
    return {
        "id": slot.get("id"),
        "path": slot.get("path"),
        "scenario": slot.get("scenario"),
        "requires_real_provider": slot.get("requires_real_provider"),
        "reference": slot.get("reference"),
        "status": "recorded",
        "ok": ok,
        "unified": unified,
        "raw": raw_payload,
    }


def _delegation_metrics(
    workspace: object,
    run_id: object,
    *,
    scenario: str,
) -> dict[str, Any]:
    if scenario not in {"validation_subagent_delegation"}:
        return {}
    if not workspace or not run_id:
        return {}
    run_dir = Path(str(workspace)) / ".asteria" / "runs" / str(run_id)
    if not run_dir.is_dir():
        return {}

    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    decisions = _read_jsonl(run_dir / "agent_loop_decisions.jsonl")
    first_action = (
        str(decisions[0].get("next_action", {}).get("action") or "")
        if decisions
        else ""
    )
    observations = _read_jsonl(run_dir / "agent_loop_observations.jsonl")
    workers = _read_jsonl(run_dir / "workers.jsonl")
    subagent_workers = [
        item for item in workers if str(item.get("worker_kind") or "") == "subagent"
    ]
    loop_summary: dict[str, Any] = {}
    loop_summary_path = run_dir / "agent_loop_run_summary.json"
    if loop_summary_path.exists():
        loop_summary = json.loads(loop_summary_path.read_text(encoding="utf-8"))

    return {
        "first_decision_action": first_action or None,
        "subagent_dispatched": first_action == "subagent",
        "subagent_child_plans": (run_dir / "subagent_child_plans.jsonl").exists(),
        "subagent_worker_count": len(subagent_workers),
        "parent_loop_rounds": loop_summary.get("rounds_completed"),
        "parent_loop_exit_reason": loop_summary.get("exit_reason"),
        "model_call_count": len(_read_jsonl(run_dir / "model_calls.jsonl")),
        "tool_call_count": len(_read_jsonl(run_dir / "tool_calls.jsonl")),
        "observation_count": len(observations),
        "post_subagent_stop_observation": any(
            item.get("observation_type") == "stop_report"
            or item.get("next_recommended_action") == "stop"
            for item in observations
        ),
    }


def _resolve_run_context(
    raw: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[Path | None, str | None]:
    workspace = raw.get("workspace")
    workspace_path = Path(str(workspace)) if workspace else None
    run_id = summary.get("run_id")
    if not run_id and workspace_path is not None:
        runs_root = workspace_path / ".asteria" / "runs"
        if runs_root.is_dir():
            candidates = sorted(
                (path for path in runs_root.iterdir() if path.is_dir()),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                run_id = candidates[0].name
    return workspace_path, str(run_id) if run_id else None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


if __name__ == "__main__":
    main()
