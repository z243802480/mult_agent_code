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
    return _summary_from_rows(path, rows, recent)


def _summary_from_rows(path: Path, rows: list[dict[str, Any]], recent: list[dict[str, Any]]) -> dict[str, Any]:
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
    active_recent, superseded = _active_rows_after_latest_acceptance(recent)
    active_summary = _summary_from_rows(path, rows, active_recent)
    priority_items = _priority_items(active_summary, active_recent)
    roadmap_tasks = [_roadmap_task(item) for item in priority_items[:5]]
    decision_points = [_decision_point(item, index + 1) for index, item in enumerate(priority_items[:3])]
    dogfooding_gate = _dogfooding_gate(active_summary, active_recent)
    acceptance_signal_gate = _acceptance_signal_gate(
        active_summary,
        active_recent,
        dogfooding_gate,
    )
    next_batch_plan = _next_batch_plan(dogfooding_gate, acceptance_signal_gate, active_recent)
    analysis = {
        "schema_version": "0.1.0",
        "created_at": now_iso(),
        "status": _analysis_status(
            priority_items,
            dogfooding_gate,
            active_summary,
            acceptance_signal_gate,
        ),
        "source": {
            "usage_signal_path": str(path),
            "total": summary["total"],
            "recent": summary["recent"],
        },
        "summary": summary,
        "active_summary": active_summary,
        "superseded_signals": superseded,
        "dogfooding_gate": dogfooding_gate,
        "acceptance_signal_gate": acceptance_signal_gate,
        "next_batch_plan": next_batch_plan,
        "priority_items": priority_items,
        "roadmap_tasks": roadmap_tasks,
        "candidate_decision_points": decision_points,
        "next_actions": _analysis_next_actions(
            priority_items,
            dogfooding_gate,
            acceptance_signal_gate,
            next_batch_plan,
        ),
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


def _active_rows_after_latest_acceptance(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latest_acceptance_index = -1
    for index, row in enumerate(rows):
        if str(row.get("artifact_outcome") or "unknown") == "accepted":
            latest_acceptance_index = index
    if latest_acceptance_index < 0:
        return rows, []
    superseded = [
        {
            "signal_id": row.get("signal_id"),
            "artifact_outcome": row.get("artifact_outcome"),
            "blocker_category": row.get("blocker_category"),
            "trust_risk": row.get("trust_risk"),
            "superseded_by_signal_id": rows[latest_acceptance_index].get("signal_id"),
            "reason": "A newer accepted artifact signal supersedes earlier unresolved operational blockers.",
        }
        for row in rows[:latest_acceptance_index]
        if str(row.get("artifact_outcome") or "unknown") in {"rejected", "blocked", "partial"}
        or str(row.get("blocker_category") or "none") != "none"
        or str(row.get("trust_risk") or "none") != "none"
    ]
    superseded_ids = {item.get("signal_id") for item in superseded}
    active = [row for row in rows if row.get("signal_id") not in superseded_ids]
    return active, superseded


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


def _dogfooding_gate(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    min_samples = 3
    sample_count = len(rows)
    accepted = sum(1 for row in rows if str(row.get("artifact_outcome") or "") == "accepted")
    unresolved = int(summary.get("unresolved") or 0)
    raw_blockers = summary.get("blockers")
    blockers: dict[str, Any] = raw_blockers if isinstance(raw_blockers, dict) else {}
    raw_trust_risks = summary.get("trust_risks")
    trust_risks: dict[str, Any] = (
        raw_trust_risks if isinstance(raw_trust_risks, dict) else {}
    )
    blocker_count = sum(int(value or 0) for value in blockers.values())
    trust_risk_count = sum(int(value or 0) for value in trust_risks.values())
    if sample_count <= 0:
        status = "missing"
        reason = "No active dogfooding usage signals exist yet."
    elif unresolved or blocker_count or trust_risk_count:
        status = "blocked"
        reason = "Active dogfooding signals include unresolved outcomes, blockers, or trust risks."
    elif sample_count < min_samples:
        status = "collecting"
        reason = f"Collect {min_samples - sample_count} more clean scoped dogfooding signal(s)."
    else:
        status = "ready"
        reason = "Active dogfooding signals meet the minimum clean-sample gate."
    return {
        "status": status,
        "sample_count": sample_count,
        "min_samples": min_samples,
        "accepted": accepted,
        "unresolved": unresolved,
        "blocker_count": blocker_count,
        "trust_risk_count": trust_risk_count,
        "ready_for_next_batch": status == "ready",
        "reason": reason,
        "evidence_refs": _recent_evidence(rows),
    }


def _acceptance_signal_gate(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    dogfooding_gate: dict[str, Any],
) -> dict[str, Any]:
    required_categories = {
        "repair_replan",
        "ask_stop",
        "context_pressure",
        "capability_selection",
    }
    accepted_by_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = _acceptance_signal_category(
            str(row.get("expected_outcome_category") or "")
        )
        if category not in required_categories:
            continue
        if str(row.get("artifact_outcome") or "") != "accepted":
            continue
        accepted_by_category[category] = row
    covered = sorted(accepted_by_category)
    missing = sorted(required_categories - set(accepted_by_category))
    unresolved = int(summary.get("unresolved") or 0)
    blocker_count = sum(int(value or 0) for value in (summary.get("blockers") or {}).values())
    trust_risk_count = sum(
        int(value or 0) for value in (summary.get("trust_risks") or {}).values()
    )
    if dogfooding_gate.get("status") == "blocked" or unresolved or blocker_count or trust_risk_count:
        status = "blocked"
        reason = "Active signals include unresolved outcomes, blockers, or trust risks."
    elif missing:
        status = "collecting"
        reason = "Collect accepted scoped validation signals for: " + ", ".join(missing)
    elif dogfooding_gate.get("status") != "ready":
        status = "collecting"
        reason = str(dogfooding_gate.get("reason") or "Dogfooding gate is not ready yet.")
    else:
        status = "ready"
        reason = "Alpha.2 scoped validation signals meet the acceptance gate."
    evidence_refs: list[str] = []
    for category in covered:
        row = accepted_by_category[category]
        evidence_refs.extend(str(ref) for ref in row.get("evidence_refs", []) if ref)
        if row.get("run_id"):
            evidence_refs.append(f"run:{row['run_id']}")
    return {
        "status": status,
        "ready_for_alpha2_next_batch": status == "ready",
        "required_categories": sorted(required_categories),
        "covered_categories": covered,
        "missing_categories": missing,
        "accepted": len(covered),
        "required": len(required_categories),
        "sample_count": int(dogfooding_gate.get("sample_count") or len(rows)),
        "reason": reason,
        "evidence_refs": list(dict.fromkeys(evidence_refs))[:12],
    }


def _analysis_status(
    priority_items: list[dict[str, Any]],
    dogfooding_gate: dict[str, Any],
    active_summary: dict[str, Any],
    acceptance_signal_gate: dict[str, Any],
) -> str:
    if priority_items or dogfooding_gate.get("status") == "blocked":
        return "needs_attention"
    if acceptance_signal_gate.get("status") == "blocked":
        return "needs_attention"
    if dogfooding_gate.get("status") in {"missing", "collecting"}:
        return "collecting"
    return str(active_summary.get("status") or "missing")


def _next_batch_plan(
    dogfooding_gate: dict[str, Any],
    acceptance_signal_gate: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if acceptance_signal_gate.get("status") != "ready":
        return {
            "status": str(acceptance_signal_gate.get("status") or "collecting"),
            "ready": False,
            "reason": str(
                acceptance_signal_gate.get("reason")
                or dogfooding_gate.get("reason")
                or "Acceptance signal gate is not ready."
            ),
            "batch_id": None,
            "max_tasks": 0,
            "task_candidates": [],
            "guardrails": _next_batch_guardrails(),
        }
    completed_categories = _completed_next_batch_categories(rows)
    required_categories = {"real_repair_task", "multi_file_small_feature", "context_pressure_maintenance"}
    if completed_categories >= required_categories:
        evidence_refs: list[str] = []
        for row in rows:
            if _next_batch_category(str(row.get("expected_outcome_category") or "")) in required_categories:
                evidence_refs.extend(str(item) for item in row.get("evidence_refs") or [])
        return {
            "status": "completed",
            "ready": False,
            "completed": True,
            "reason": "Alpha.2 next scoped dogfooding batch has accepted evidence for all required task categories.",
            "batch_id": "alpha2-next-scoped-dogfooding",
            "max_tasks": 3,
            "completed_categories": sorted(completed_categories),
            "missing_categories": [],
            "task_candidates": [],
            "evidence_refs": list(dict.fromkeys(evidence_refs))[:12],
            "guardrails": _next_batch_guardrails(),
        }
    return {
        "status": "ready",
        "ready": True,
        "completed": False,
        "reason": "Alpha.2 acceptance signals support the next scoped dogfooding batch.",
        "batch_id": "alpha2-next-scoped-dogfooding",
        "max_tasks": 3,
        "completed_categories": sorted(completed_categories),
        "missing_categories": sorted(required_categories - completed_categories),
        "task_candidates": [
            {
                "id": "real_repair_task",
                "title": "Run one real repair task with failing or explicit acceptance evidence.",
                "task_kind": "repair_validation",
                "value": "Proves repair/replan moves a realistic user-facing task forward.",
                "required_evidence": [
                    "run final_report.md",
                    "validation or explicit acceptance evidence",
                    "accepted usage signal",
                ],
            },
            {
                "id": "multi_file_small_feature",
                "title": "Run one 2-4 file feature task without enabling real parallel writes.",
                "task_kind": "multi_file_feature",
                "value": "Exercises planning, scope control, final report, and promotion guardrails.",
                "required_evidence": [
                    "task_plan write_scope",
                    "changed artifact evidence",
                    "accepted usage signal",
                ],
            },
            {
                "id": "context_pressure_maintenance",
                "title": "Run one context-heavy maintenance task over docs and source slices.",
                "task_kind": "context_pressure_validation",
                "value": "Proves context budget and compact-boundary evidence remain understandable.",
                "required_evidence": [
                    "context_budget_snapshots.jsonl",
                    "run final_report.md",
                    "accepted usage signal",
                ],
            },
        ],
        "guardrails": _next_batch_guardrails(),
    }


def _next_batch_guardrails() -> list[str]:
    return [
        "Keep real_disjoint_write_workers disabled.",
        "Limit the next batch to at most 3 scoped tasks.",
        "Bind every completed task to usage_signal evidence refs.",
        "Export a fresh evidence bundle after the batch.",
        "Treat provider/network instability as route evidence, not immediate product direction.",
    ]


def _completed_next_batch_categories(rows: list[dict[str, Any]]) -> set[str]:
    completed: set[str] = set()
    for row in rows:
        if str(row.get("artifact_outcome") or "unknown") != "accepted":
            continue
        category = _next_batch_category(str(row.get("expected_outcome_category") or ""))
        if category:
            completed.add(category)
    return completed


def _next_batch_category(category: str) -> str | None:
    aliases = {
        "real_repair_task": "real_repair_task",
        "multi_file_small_feature": "multi_file_small_feature",
        "context_pressure_maintenance": "context_pressure_maintenance",
    }
    return aliases.get(category)


def _acceptance_signal_category(category: str) -> str:
    aliases = {
        "repair_replan_path": "repair_replan",
        "recovery_path": "repair_replan",
        "ask_stop_path": "ask_stop",
        "ask_stop_boundary": "ask_stop",
        "context_pressure_path": "context_pressure",
        "capability_selection_path": "capability_selection",
    }
    return aliases.get(category, category)


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


def _analysis_next_actions(
    items: list[dict[str, Any]],
    dogfooding_gate: dict[str, Any],
    acceptance_signal_gate: dict[str, Any],
    next_batch_plan: dict[str, Any],
) -> list[str]:
    if not items:
        if next_batch_plan.get("status") == "completed":
            return [
                "Alpha.2 next scoped dogfooding batch is complete; export a fresh evidence bundle and choose the next gated development lane."
            ]
        if next_batch_plan.get("ready"):
            return [
                "Next batch plan is ready; run at most 3 scoped dogfooding tasks and bind each result to usage signals."
            ]
        if acceptance_signal_gate.get("status") == "ready":
            return [
                "Acceptance signal gate is ready; prepare the alpha.2 evidence bundle and next scoped dogfooding batch."
            ]
        if acceptance_signal_gate.get("status") == "collecting":
            return [
                str(
                    acceptance_signal_gate.get("reason")
                    or "Continue collecting accepted scoped validation signals."
                )
            ]
        if dogfooding_gate.get("status") == "ready":
            return ["Dogfooding signal gate is ready; continue with the next scoped batch."]
        return [str(dogfooding_gate.get("reason") or "Continue collecting background usage signals during scoped dogfooding.")]
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
