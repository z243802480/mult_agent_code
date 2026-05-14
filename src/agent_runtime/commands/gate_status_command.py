from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateStatusResult:
    root: Path
    stage: str
    gate_report: dict[str, Any] = field(default_factory=dict)
    gray_report: dict[str, Any] = field(default_factory=dict)
    core_report: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        blocking_reason = self.next_actions[0] if self.next_actions else None
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "stage": self.stage,
            "release_ready": self.stage == "ready_for_small_real_task_gray",
            "blocking_reason": blocking_reason,
            "gates": {
                "real_model_gate": self._gate_summary(self.gate_report),
                "gray_suite": self._gate_summary(self.gray_report, gray=True),
                "core_acceptance": self._gate_summary(self.core_report),
            },
            "gate_report": self.gate_report,
            "gray_report": self.gray_report,
            "core_report": self.core_report,
            "next_actions": self.next_actions,
        }

    def _gate_summary(self, report: dict[str, Any], gray: bool = False) -> dict[str, Any]:
        if not report:
            return {"present": False, "ok": None, "status": "missing"}
        summary: dict[str, Any] = {
            "present": True,
            "ok": bool(report.get("ok")),
            "status": "pass" if report.get("ok") else "fail",
        }
        aggregate = report.get("aggregate")
        if isinstance(aggregate, dict):
            summary["total"] = int(aggregate.get("total") or 0)
            summary["passed"] = int(aggregate.get("passed") or 0)
            summary["failed"] = int(aggregate.get("failed") or 0)
        if gray:
            summary["gray_ready"] = report.get("gray_ready")
            route = aggregate.get("route_evidence") if isinstance(aggregate, dict) else {}
            if isinstance(route, dict):
                summary["route_evidence"] = route
        return summary

    def to_text(self) -> str:
        lines = [
            "Gate status",
            f"Root: {self.root}",
            f"Stage: {self.stage}",
        ]
        lines.extend(self._report_lines("Real model gate", self.gate_report))
        lines.extend(self._report_lines("Gray suite", self.gray_report, gray=True))
        lines.extend(self._report_lines("Core acceptance", self.core_report))
        if self.next_actions:
            lines.append("Recommended next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)

    def _report_lines(self, label: str, report: dict[str, Any], gray: bool = False) -> list[str]:
        if not report:
            return [f"{label}: missing"]
        status = "pass" if report.get("ok") else "fail"
        lines = [f"{label}: {status}"]
        if gray and "gray_ready" in report:
            lines.append(f"  gray_ready: {report.get('gray_ready')}")
        aggregate = report.get("aggregate")
        if isinstance(aggregate, dict):
            lines.append(
                "  scenarios: "
                f"{aggregate.get('passed', 0)}/{aggregate.get('total', 0)} passed"
            )
            route = aggregate.get("route_evidence")
            if isinstance(route, dict):
                lines.append(
                    "  routes: "
                    f"strong={route.get('strong_used', False)}, "
                    f"medium={route.get('medium_used', False)}"
                )
        failures = report.get("failures")
        if isinstance(failures, list) and failures:
            lines.append("  failures: " + "; ".join(str(item) for item in failures[:3]))
        return lines


class GateStatusCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> GateStatusResult:
        gate = self._read_json(self.root / ".agent" / "model" / "real_model_gate_report.json")
        gray = self._read_json(
            self.root / ".agent" / "verification" / "real_model_acceptance_gray.json"
        )
        core = self._read_json(
            self.root / ".agent" / "verification" / "real_model_acceptance_core.json"
        ) or self._read_json(self.root / ".agent" / "acceptance" / "acceptance_report.json")
        stage, actions = self._stage(gate, gray, core)
        return GateStatusResult(
            root=self.root,
            stage=stage,
            gate_report=gate,
            gray_report=gray,
            core_report=core,
            next_actions=actions,
        )

    def _stage(
        self,
        gate: dict[str, Any],
        gray: dict[str, Any],
        core: dict[str, Any],
    ) -> tuple[str, list[str]]:
        if not gate:
            return (
                "missing_real_model_gate",
                ["Run `python scripts/real_model_gate.py --summary-json .agent/model/real_model_gate_report.json`."],
            )
        if not gate.get("ok"):
            return ("real_model_gate_failed", list(gate.get("recommended_actions") or []))
        if not gray:
            return (
                "ready_for_gray_suite",
                ["Run `python scripts/real_model_acceptance.py --suite gray --summary-json .agent/verification/real_model_acceptance_gray.json`."],
            )
        if not gray.get("ok") or gray.get("gray_ready") is not True:
            return (
                "gray_suite_failed",
                ["Inspect gray suite evidence; do not proceed to core acceptance yet."],
            )
        if not core:
            return (
                "ready_for_core_acceptance",
                ["Run `python scripts/real_model_acceptance.py --suite core --summary-json .agent/verification/real_model_acceptance_core.json`."],
            )
        if not core.get("ok"):
            return ("core_acceptance_failed", ["Repair core acceptance failures before release."])
        return ("ready_for_small_real_task_gray", ["Start small real-task gray validation."])

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
