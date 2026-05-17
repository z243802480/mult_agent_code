from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.models.route_diagnostics import route_environment_for_tiers


@dataclass(frozen=True)
class GateStatusResult:
    root: Path
    stage: str
    gate_report: dict[str, Any] = field(default_factory=dict)
    gray_report: dict[str, Any] = field(default_factory=dict)
    core_report: dict[str, Any] = field(default_factory=dict)
    route_environment: dict[str, Any] = field(default_factory=dict)
    validation_recommendation: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rollout_state = self._rollout_state()
        blocking_reason = (
            None
            if rollout_state == "release_ready"
            else (self.next_actions[0] if self.next_actions else None)
        )
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "stage": self.stage,
            "rollout_state": rollout_state,
            "release_ready": rollout_state == "release_ready",
            "blocking_reason": blocking_reason,
            "gates": {
                "real_model_gate": self._gate_summary(self.gate_report),
                "gray_suite": self._gate_summary(self.gray_report, gray=True),
                "core_acceptance": self._gate_summary(self.core_report),
            },
            "route_environment": self.route_environment,
            "gray_task_limits": _gray_task_limits(),
            "validation_recommendation": self.validation_recommendation,
            "gate_report": self.gate_report,
            "gray_report": self.gray_report,
            "core_report": self.core_report,
            "next_actions": self.next_actions,
        }

    def _rollout_state(self) -> str:
        if self.stage == "current_environment_incomplete":
            return "blocked"
        if self.stage == "ready_for_small_real_task_gray":
            return "release_ready"
        if self.stage in {"ready_for_gray_suite", "ready_for_core_acceptance"}:
            return "conditional"
        return "blocked"

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
            f"Rollout state: {self._rollout_state()}",
        ]
        if self.route_environment:
            lines.append(
                "Current routes: "
                f"strong={self.route_environment.get('strong', {}).get('configured', False)}, "
                f"medium={self.route_environment.get('medium', {}).get('configured', False)}"
            )
        lines.extend(self._report_lines("Real model gate", self.gate_report))
        lines.extend(self._report_lines("Gray suite", self.gray_report, gray=True))
        lines.extend(self._report_lines("Core acceptance", self.core_report))
        if self.next_actions:
            lines.append("Recommended next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        if self.validation_recommendation:
            lines.append("Recommended validation:")
            lines.append(f"  - level: {self.validation_recommendation.get('level')}")
            lines.append(f"  - command: {self.validation_recommendation.get('command')}")
        limits = _gray_task_limits()
        lines.append("Small gray task limits:")
        lines.append(f"  - max_iterations: {limits['max_iterations']}")
        lines.append(f"  - max_tasks_per_iteration: {limits['max_tasks_per_iteration']}")
        lines.append(f"  - max_repairs: {limits['max_repairs']}")
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
                f"  scenarios: {aggregate.get('passed', 0)}/{aggregate.get('total', 0)} passed"
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
        gate = self._read_json(self.root / ".asteria" / "model" / "real_model_gate_report.json")
        gray = self._read_json(
            self.root / ".asteria" / "verification" / "real_model_acceptance_gray.json"
        )
        core = self._read_json(
            self.root / ".asteria" / "verification" / "real_model_acceptance_core.json"
        ) or self._read_json(self.root / ".asteria" / "acceptance" / "acceptance_report.json")
        stage, actions = self._stage(gate, gray, core)
        route_environment = _route_environment()
        if stage == "ready_for_small_real_task_gray" and not route_environment["ready"]:
            stage = "current_environment_incomplete"
            missing = ", ".join(route_environment["missing_required"])
            actions = [
                f"Set current model route environment variables before gray validation: {missing}.",
                *actions,
            ]
        return GateStatusResult(
            root=self.root,
            stage=stage,
            gate_report=gate,
            gray_report=gray,
            core_report=core,
            route_environment=route_environment,
            validation_recommendation=_validation_recommendation(self.root),
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
                [
                    "Run `python scripts/real_model_gate.py --summary-json .asteria/model/real_model_gate_report.json`."
                ],
            )
        if not gate.get("ok"):
            return ("real_model_gate_failed", list(gate.get("recommended_actions") or []))
        if not gray:
            return (
                "ready_for_gray_suite",
                [
                    "Run `python scripts/real_model_acceptance.py --suite gray --summary-json .asteria/verification/real_model_acceptance_gray.json`."
                ],
            )
        if not gray.get("ok") or gray.get("gray_ready") is not True:
            return (
                "gray_suite_failed",
                ["Inspect gray suite evidence; do not proceed to core acceptance yet."],
            )
        if not core:
            return (
                "ready_for_core_acceptance",
                [
                    "Run `python scripts/real_model_acceptance.py --suite core --summary-json .asteria/verification/real_model_acceptance_core.json`."
                ],
            )
        if not core.get("ok"):
            return ("core_acceptance_failed", ["Repair core acceptance failures before release."])
        return (
            "ready_for_small_real_task_gray",
            [
                "Start small real-task gray validation with `--max-iterations 3 --max-tasks-per-iteration 1 --no-research`.",
                "Stop and collect evidence if cost status reaches near_limit or a merge/protected-path risk appears.",
            ],
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def _gray_task_limits() -> dict[str, object]:
    return {
        "max_iterations": 3,
        "max_tasks_per_iteration": 1,
        "max_repairs": 1,
        "max_replans": 1,
        "recommended_run_flags": [
            "--max-iterations 3",
            "--max-tasks-per-iteration 1",
            "--no-research",
        ],
        "stop_conditions": [
            "cost_status near_limit or hard_stop",
            "merge gate promotion risk",
            "protected path risk",
            "session cannot resume",
        ],
    }


def _route_environment() -> dict[str, Any]:
    return route_environment_for_tiers(("strong", "medium"))


def _validation_recommendation(root: Path) -> dict[str, Any]:
    changed_files = _changed_files(root)
    return _validation_recommendation_for_changed_files(changed_files)


def _changed_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    files = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        files.append(path.replace("\\", "/"))
    return files


def _validation_recommendation_for_changed_files(changed_files: list[str]) -> dict[str, Any]:
    if not changed_files:
        return {
            "level": "none",
            "reason": "No git changes detected or git status unavailable.",
            "changed_file_count": 0,
            "command": "asteria gate-status --json",
        }
    source_changes = [
        path
        for path in changed_files
        if path.startswith(("src/", "tests/", "schemas/", "scripts/"))
    ]
    runtime_changes = [
        path
        for path in changed_files
        if path.startswith(
            (
                "src/asteria_runtime/core/",
                "src/asteria_runtime/commands/",
                "src/asteria_runtime/acceptance/",
                "src/asteria_runtime/models/",
            )
        )
    ]
    docs_only = all(path.startswith("docs/") or path.endswith(".md") for path in changed_files)
    if docs_only:
        return {
            "level": "targeted",
            "reason": "Only documentation changed.",
            "changed_file_count": len(changed_files),
            "command": "ruff check .",
        }
    if len(changed_files) >= 12 or len(runtime_changes) >= 4:
        return {
            "level": "full_gray_core",
            "reason": "Broad Runtime OS changes detected.",
            "changed_file_count": len(changed_files),
            "command": (
                "ruff check . && mypy src && pytest -q && "
                "asteria real-model-gate && asteria real-model-acceptance --suite gray && "
                "asteria /acceptance-gate --suite core"
            ),
        }
    if source_changes:
        return {
            "level": "core_subset",
            "reason": "Runtime source or test files changed.",
            "changed_file_count": len(changed_files),
            "command": "ruff check . && mypy src && pytest -q && asteria /acceptance-gate --suite core --min-scenarios 6",
        }
    return {
        "level": "targeted",
        "reason": "Small non-runtime change detected.",
        "changed_file_count": len(changed_files),
        "command": "ruff check . && pytest -q",
    }
