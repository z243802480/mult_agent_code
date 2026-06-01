from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


USAGE_SIGNAL_PATH = Path("ops") / "usage_signals.jsonl"


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


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _allowed(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default
