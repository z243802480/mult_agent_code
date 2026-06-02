from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.usage_signal import (
    UsageSignalInput,
    UsageSignalRecorder,
    usage_signal_analysis,
    usage_signal_summary,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class OpsSignalResult:
    root: Path
    signal: dict[str, Any] | None
    summary: dict[str, Any]
    analysis: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "signal": self.signal,
            "summary": self.summary,
            "analysis": self.analysis,
        }

    def to_text(self) -> str:
        lines = [
            "Ops usage signal",
            f"Root: {self.root}",
            f"Status: {self.summary.get('status')}",
            f"Total signals: {self.summary.get('total')}",
            f"Unresolved: {self.summary.get('unresolved')}",
            f"Path: {self.summary.get('path')}",
        ]
        if self.signal:
            lines.insert(2, f"Recorded: {self.signal.get('signal_id')}")
        if self.analysis:
            lines.append(f"Analysis status: {self.analysis.get('status')}")
            gate = self.analysis.get("dogfooding_gate")
            if isinstance(gate, dict):
                lines.append(
                    "Dogfooding gate: "
                    f"{gate.get('status')} "
                    f"({gate.get('sample_count')}/{gate.get('min_samples')} samples)"
                )
            lines.append(f"Priority items: {len(self.analysis.get('priority_items') or [])}")
            lines.append(f"Roadmap tasks: {len(self.analysis.get('roadmap_tasks') or [])}")
        return "\n".join(lines)


class OpsSignalCommand:
    def __init__(
        self,
        root: Path,
        *,
        run_id: str | None = None,
        task_kind: str = "unknown",
        expected_outcome_category: str = "unknown",
        artifact_outcome: str = "unknown",
        blocker_category: str = "none",
        trust_risk: str = "none",
        summary: str = "",
        evidence_refs: list[str] | None = None,
        source: str = "maintainer_cli",
        summarize_only: bool = False,
        analyze: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.task_kind = task_kind
        self.expected_outcome_category = expected_outcome_category
        self.artifact_outcome = artifact_outcome
        self.blocker_category = blocker_category
        self.trust_risk = trust_risk
        self.summary = summary
        self.evidence_refs = evidence_refs or []
        self.source = source
        self.summarize_only = summarize_only
        self.analyze = analyze
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> OpsSignalResult:
        agent_dir = self.root / ".asteria"
        signal = None
        if not self.summarize_only:
            signal = UsageSignalRecorder(self.validator).record(
                agent_dir,
                UsageSignalInput(
                    run_id=self.run_id,
                    task_kind=self.task_kind,
                    expected_outcome_category=self.expected_outcome_category,
                    artifact_outcome=self.artifact_outcome,
                    blocker_category=self.blocker_category,
                    trust_risk=self.trust_risk,
                    summary=self.summary,
                    evidence_refs=self.evidence_refs,
                    source=self.source,
                ),
            )
        analysis = usage_signal_analysis(agent_dir, self.validator, write=True) if self.analyze else None
        return OpsSignalResult(
            root=self.root,
            signal=signal,
            summary=usage_signal_summary(agent_dir, self.validator),
            analysis=analysis,
        )
