from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def latest_real_provider_matrix(agent_dir: Path) -> dict[str, Any]:
    """Return a compact summary for the latest real-provider P0 matrix run."""

    matrix_dir = agent_dir / "verification" / "real_provider_matrix"
    if not matrix_dir.exists():
        return {}
    candidates: list[tuple[str, float, Path, dict[str, Any]]] = []
    for path in matrix_dir.glob("*/matrix_summary.json"):
        summary = _read_json(path)
        if not summary:
            continue
        created_at = str(summary.get("created_at") or "")
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        candidates.append((created_at, modified, path, summary))
    if not candidates:
        return {}
    _created_at, _modified, path, summary = max(
        candidates,
        key=lambda item: (item[0], item[1], item[2].as_posix()),
    )
    return summarize_real_provider_matrix(summary, path)


def summarize_real_provider_matrix(
    summary: dict[str, Any],
    summary_path: Path | None = None,
) -> dict[str, Any]:
    cases = [item for item in summary.get("cases") or [] if isinstance(item, dict)]
    failed_cases = [case for case in cases if case.get("ok") is not True]
    latest_case = failed_cases[-1] if failed_cases else (cases[-1] if cases else {})
    route = str(latest_case.get("route") or "unknown") if latest_case else "unknown"
    reason = str(latest_case.get("reason") or "No reason recorded.") if latest_case else ""
    evidence_refs = [str(ref) for ref in latest_case.get("evidence_refs") or []][:5]
    failed_summaries = [
        {
            "name": case.get("name"),
            "task_kind": case.get("task_kind"),
            "route": case.get("route"),
            "reason": case.get("reason"),
            "failure_summary": case.get("failure_summary"),
            "evidence_refs": [str(ref) for ref in case.get("evidence_refs") or []][:5],
        }
        for case in failed_cases[:5]
    ]
    result: dict[str, Any] = {
        "matrix": summary.get("matrix"),
        "created_at": summary.get("created_at"),
        "ok": bool(summary.get("ok")),
        "case_count": int(summary.get("case_count") or len(cases)),
        "passed": int(summary.get("passed") or 0),
        "failed": int(summary.get("failed") or len(failed_cases)),
        "latest_case": latest_case.get("name") if latest_case else None,
        "latest_task_kind": latest_case.get("task_kind") if latest_case else None,
        "latest_route": route,
        "latest_reason": reason,
        "latest_evidence_refs": evidence_refs,
        "failed_cases": failed_summaries,
    }
    if summary_path is not None:
        result["summary_path"] = str(summary_path)
    return result


def real_provider_matrix_text_lines(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return []
    lines = [
        "Latest real-provider matrix: "
        f"{matrix.get('passed', 0)}/{matrix.get('case_count', 0)} passed "
        f"(ok={matrix.get('ok', False)})",
        "  route: "
        f"{matrix.get('latest_route', 'unknown')} "
        f"task={matrix.get('latest_task_kind', 'unknown')} "
        f"case={matrix.get('latest_case', 'unknown')}",
        f"  reason: {matrix.get('latest_reason') or 'No reason recorded.'}",
    ]
    evidence_refs = matrix.get("latest_evidence_refs") or []
    if evidence_refs:
        lines.append(f"  evidence: {', '.join(str(ref) for ref in evidence_refs[:3])}")
    summary_path = matrix.get("summary_path")
    if summary_path:
        lines.append(f"  summary: {summary_path}")
    failed_cases = matrix.get("failed_cases") or []
    if failed_cases:
        lines.append("  failed routes:")
        for case in failed_cases[:3]:
            lines.append(
                "    - "
                f"{case.get('name', 'unknown')}: "
                f"{case.get('route', 'unknown')} "
                f"({case.get('failure_summary') or case.get('reason') or 'no summary'})"
            )
    return lines


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}
