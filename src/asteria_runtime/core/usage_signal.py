from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


USAGE_SIGNAL_PATH = Path("ops") / "usage_signals.jsonl"
USAGE_SIGNAL_ANALYSIS_PATH = Path("ops") / "usage_signal_analysis.json"


@dataclass(frozen=True)
class UsageSignalInput:
    run_id: str | None = None
    task_kind: str = "unknown"
    expected_outcome_category: str = "unknown"
    artifact_outcome: str = "unknown"
    blocker_category: str = "none"
    trust_risk: str = "none"
    summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    source: str = "maintainer_cli"


class UsageSignalRecorder:
    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator
        self.jsonl = JsonlStore(validator)

    def record(self, agent_dir: Path, signal: UsageSignalInput) -> dict[str, Any]:
        path = agent_dir / USAGE_SIGNAL_PATH
        rows = self.jsonl.read_all(path, "usage_signal") if path.exists() else []
        payload = {
            "schema_version": "0.1.0",
            "signal_id": f"usage-signal-{len(rows) + 1:04d}",
            "created_at": now_iso(),
            "source": signal.source,
            "run_id": signal.run_id,
            "task_kind": signal.task_kind or "unknown",
            "expected_outcome_category": signal.expected_outcome_category or "unknown",
            "artifact_outcome": _allowed(
                signal.artifact_outcome,
                {"accepted", "rejected", "blocked", "partial", "unknown"},
                "unknown",
            ),
            "blocker_category": signal.blocker_category or "none",
            "trust_risk": signal.trust_risk or "none",
            "summary": signal.summary or "",
            "evidence_refs": signal.evidence_refs,
            "redacted": True,
        }
        self.jsonl.append(path, payload, "usage_signal")
        return payload


def usage_signal_summary(agent_dir: Path, validator: SchemaValidator, *, limit: int = 50) -> dict[str, Any]:
    path = agent_dir / USAGE_SIGNAL_PATH
    rows = JsonlStore(validator).read_all(path, "usage_signal") if path.exists() else []
    recent = rows[-limit:]
    outcomes = _counts(str(row.get("artifact_outcome") or "unknown") for row in recent)
    blockers = _counts(
        str(row.get("blocker_category") or "none")
        for row in recent
        if str(row.get("blocker_category") or "none") != "none"
    )
    trust_risks = _counts(
        str(row.get("trust_risk") or "none")
        for row in recent
        if str(row.get("trust_risk") or "none") != "none"
    )
    unresolved = sum(
        1
        for row in recent
        if str(row.get("artifact_outcome") or "unknown") in {"rejected", "blocked", "partial"}
    )
    latest = recent[-1] if recent else {}
    status = "missing"
    if recent:
        status = "needs_attention" if unresolved or blockers or trust_risks else "healthy"
    return {
        "status": status,
        "path": str(path),
        "total": len(rows),
        "recent": len(recent),
        "unresolved": unresolved,
        "outcomes": outcomes,
        "blockers": blockers,
        "trust_risks": trust_risks,
        "latest_signal_id": latest.get("signal_id"),
        "latest_run_id": latest.get("run_id"),
        "latest_summary": latest.get("summary"),
    }


def usage_signal_analysis(
    agent_dir: Path,
    validator: SchemaValidator,
    *,
    limit: int = 50,
    write: bool = False,
) -> dict[str, Any]:
    path = agent_dir / USAGE_SIGNAL_PATH
    rows = JsonlStore(validator).read_all(path, "usage_signal") if path.exists() else []
    recent = rows[-limit:]
    summary = usage_signal_summary(agent_dir, validator, limit=limit)
    priority_items = _priority_items(summary, recent)
    roadmap_tasks = [_roadmap_task(item) for item in priority_items[:5]]
    decision_points = [_decision_point(item, index + 1) for index, item in enumerate(priority_items[:3])]
    analysis = {
        "schema_version": "0.1.0",
        "created_at": now_iso(),
        "status": "needs_attention" if priority_items else summary["status"],
        "source": {
            "usage_signal_path": str(path),
            "total": summary["total"],
            "recent": summary["recent"],
        },
        "summary": summary,
        "priority_items": priority_items,
        "roadmap_tasks": roadmap_tasks,
        "candidate_decision_points": decision_points,
        "next_actions": _analysis_next_actions(priority_items),
    }
    if write:
        JsonStore(validator).write(agent_dir / USAGE_SIGNAL_ANALYSIS_PATH, analysis, "usage_signal_analysis")
    return analysis


def latest_usage_signal_analysis(agent_dir: Path, validator: SchemaValidator) -> dict[str, Any]:
    path = agent_dir / USAGE_SIGNAL_ANALYSIS_PATH
    if not path.exists():
        return usage_signal_analysis(agent_dir, validator)
    return JsonStore(validator).read(path, "usage_signal_analysis")


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _allowed(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _priority_items(summary: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    if int(summary.get("unresolved") or 0):
        items.append(
            {
                "id": "usage-unresolved-artifacts",
                "kind": "artifact_outcome",
                "severity": "high",
                "count": int(summary["unresolved"]),
                "title": "Resolve unresolved artifact outcomes before widening dogfooding.",
                "evidence_refs": _recent_evidence(rows, {"rejected", "blocked", "partial"}),
            }
        )
    for category, count in list((summary.get("blockers") or {}).items())[:3]:
        items.append(
            {
                "id": f"usage-blocker-{_slug(category)}",
                "kind": "blocker_category",
                "severity": "high" if count >= 2 else "medium",
                "count": int(count),
                "title": f"Reduce repeated blocker category: {category}.",
                "evidence_refs": _recent_evidence(rows, blocker=category),
            }
        )
    for risk, count in list((summary.get("trust_risks") or {}).items())[:3]:
        items.append(
            {
                "id": f"usage-trust-{_slug(risk)}",
                "kind": "trust_risk",
                "severity": "high" if count >= 2 else "medium",
                "count": int(count),
                "title": f"Repair repeated trust risk: {risk}.",
                "evidence_refs": _recent_evidence(rows, trust_risk=risk),
            }
        )
    return sorted(items, key=lambda item: (_severity_rank(item["severity"]), -int(item["count"])))


def _roadmap_task(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": f"ops-{item['id']}",
        "title": item["title"],
        "priority": "P0" if item["severity"] == "high" else "P1",
        "source": "usage_signal_analysis",
        "evidence_refs": item.get("evidence_refs", []),
    }


def _decision_point(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "decision_id": f"ops-signal-decision-{index:04d}",
        "status": "pending",
        "question": f"How should Asteria address: {item['title']}",
        "recommended_option_id": "create_task",
        "options": [
            {
                "option_id": "create_task",
                "label": "Create repair task",
                "tradeoff": "Turns repeated operational evidence into planned product work.",
                "action": "create_task",
            },
            {
                "option_id": "record_constraint",
                "label": "Keep as constraint",
                "tradeoff": "Preserves the signal without expanding implementation scope yet.",
                "action": "record_constraint",
            },
        ],
        "default_option_id": "create_task",
        "impact": {"scope": "medium", "budget": "medium", "risk": "medium", "quality": "high"},
        "selected_option_id": None,
        "created_at": now_iso(),
        "metadata": {
            "source": "usage_signal_analysis",
            "priority_item_id": item["id"],
            "evidence_refs": item.get("evidence_refs", []),
        },
        "resolved_at": None,
    }


def _analysis_next_actions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["Continue collecting background usage signals during scoped dogfooding."]
    return [
        "Review `.asteria/ops/usage_signal_analysis.json`.",
        "Promote high-priority roadmap_tasks into the next bounded development cycle.",
        "Create or resolve candidate_decision_points before widening dogfooding.",
    ]


def _recent_evidence(
    rows: list[dict[str, Any]],
    outcomes: set[str] | None = None,
    *,
    blocker: str | None = None,
    trust_risk: str | None = None,
) -> list[str]:
    refs: list[str] = []
    for row in reversed(rows):
        if outcomes and str(row.get("artifact_outcome")) not in outcomes:
            continue
        if blocker and row.get("blocker_category") != blocker:
            continue
        if trust_risk and row.get("trust_risk") != trust_risk:
            continue
        refs.extend(str(ref) for ref in row.get("evidence_refs", []) if ref)
        if row.get("run_id"):
            refs.append(f"run:{row['run_id']}")
        if len(refs) >= 5:
            break
    return list(dict.fromkeys(refs))[:5]


def _severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def _slug(value: str) -> str:
    normalized = "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")
    return normalized or "unknown"
