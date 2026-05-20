from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.run_command import RunCommand, RunResult
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


DEFAULT_GRAY_GOAL = (
    "Create a tiny local gray validation artifact named gray_probe.txt containing one line: "
    "gray small task ok. Keep the change minimal and verify the file exists."
)


@dataclass(frozen=True)
class GrayRunResult:
    gray_run_id: str
    status: str
    summary_path: Path
    run_id: str | None = None
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "gray_run_id": self.gray_run_id,
            "status": self.status,
            "summary_path": str(self.summary_path),
            "run_id": self.run_id,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            f"Gray run: {self.gray_run_id}",
            f"Status: {self.status}",
            f"Summary: {self.summary_path}",
        ]
        if self.run_id:
            lines.append(f"Run: {self.run_id}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class GrayRunCommand:
    def __init__(
        self,
        root: Path,
        goal: str | None = None,
        *,
        dry_run: bool = False,
        max_iterations: int = 3,
        max_tasks_per_iteration: int = 1,
        summary_json: Path | None = None,
        run_command_factory: Callable[..., RunCommand] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal or DEFAULT_GRAY_GOAL
        self.dry_run = dry_run
        self.max_iterations = max_iterations
        self.max_tasks_per_iteration = max_tasks_per_iteration
        self.validator = SchemaValidator(schema_dir())
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.run_command_factory = run_command_factory or RunCommand
        self.summary_json = summary_json

    def run(self) -> GrayRunResult:
        gray_run_id = self._gray_run_id()
        summary_path = self._summary_path(gray_run_id)
        version = VersionCommand().run().to_dict()
        package = PackageCheckCommand(self.root).run().to_dict()
        doctor = DoctorCommand(self.root).run()
        gate = GateStatusCommand(self.root).run()
        goal_spec_route_plan = CapabilityFeedbackAdvisor(
            self.validator
        ).goal_spec_execution_plan(self.root / ".asteria", self.goal)
        blocked_reasons = self._blocked_reasons(doctor.to_dict(), gate.to_dict())
        if blocked_reasons:
            summary = self._build_summary(
                gray_run_id=gray_run_id,
                status="blocked",
                summary_path=summary_path,
                version=version,
                package=package,
                doctor=doctor.to_dict(),
                gate=gate.to_dict(),
                goal_spec_route_plan=goal_spec_route_plan,
                run_result=None,
                evidence={},
                next_actions=blocked_reasons,
            )
            self.store.write(summary_path, summary, "gray_run")
            return GrayRunResult(gray_run_id, "blocked", summary_path, None, blocked_reasons)

        if self.dry_run:
            actions = ["Run without `--dry-run` to start the controlled small real-task gray run."]
            summary = self._build_summary(
                gray_run_id=gray_run_id,
                status="dry_run",
                summary_path=summary_path,
                version=version,
                package=package,
                doctor=doctor.to_dict(),
                gate=gate.to_dict(),
                goal_spec_route_plan=goal_spec_route_plan,
                run_result=None,
                evidence={},
                next_actions=actions,
            )
            self.store.write(summary_path, summary, "gray_run")
            return GrayRunResult(gray_run_id, "dry_run", summary_path, None, actions)

        run_command = self.run_command_factory(
            root=self.root,
            goal=self.goal,
            max_iterations=self.max_iterations,
            max_tasks_per_iteration=self.max_tasks_per_iteration,
            enable_research=False,
            parallel_writes=False,
        )
        run_result = run_command.run()
        evidence = self._evidence(run_result.run_id)
        status = self._status_from_run(run_result, evidence)
        actions = self._next_actions(status, run_result.run_id, evidence)
        summary = self._build_summary(
            gray_run_id=gray_run_id,
            status=status,
            summary_path=summary_path,
            version=version,
            package=package,
            doctor=doctor.to_dict(),
            gate=gate.to_dict(),
            goal_spec_route_plan=goal_spec_route_plan,
            run_result=self._run_result_dict(run_result),
            evidence=evidence,
            next_actions=actions,
        )
        self.store.write(summary_path, summary, "gray_run")
        return GrayRunResult(gray_run_id, status, summary_path, run_result.run_id, actions)

    def _blocked_reasons(self, doctor: dict[str, object], gate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if doctor.get("ok") is not True:
            reasons.append("Fix `asteria doctor` error checks before gray-run.")
        if gate.get("stage") != "ready_for_small_real_task_gray":
            blocking_reason = gate.get("blocking_reason")
            if blocking_reason:
                reasons.append(str(blocking_reason))
            else:
                reasons.append(
                    "Reach `ready_for_small_real_task_gray` via real model gate, gray suite, and core acceptance."
                )
        route_guidance = gate.get("route_guidance")
        if isinstance(route_guidance, dict) and route_guidance.get("status") == "blocked":
            reasons.extend(str(item) for item in route_guidance.get("recommended_actions", []))
        return reasons

    def _build_summary(
        self,
        *,
        gray_run_id: str,
        status: str,
        summary_path: Path,
        version: dict[str, object],
        package: dict[str, object],
        doctor: dict[str, object],
        gate: dict[str, Any],
        goal_spec_route_plan: dict[str, Any],
        run_result: dict[str, Any] | None,
        evidence: dict[str, Any],
        next_actions: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "gray_run_id": gray_run_id,
            "created_at": now_iso(),
            "root": str(self.root),
            "status": status,
            "dry_run": self.dry_run,
            "goal": self.goal,
            "preflight": {
                "sequence": [
                    "version",
                    "package-check",
                    "doctor",
                    "gate-status",
                    "gray-run",
                ],
                "version": version,
                "package_check": package,
                "doctor": doctor,
                "gate_status": gate,
            },
            "budgets": {
                "max_iterations": self.max_iterations,
                "max_tasks_per_iteration": self.max_tasks_per_iteration,
                "research_enabled": False,
                "parallel_writes": False,
            },
            "route_expectations": {
                "planning_coordinator": "strong",
                "worker": "medium",
                "strong_provider_target": "GLM 5.1 or configured strong route",
                "medium_provider_target": "MiniMax or configured medium route",
                "goal_spec_execution_plan": goal_spec_route_plan,
            },
            "run_id": run_result["run_id"] if run_result else None,
            "run_result": run_result,
            "evidence": evidence,
            "summary_path": str(summary_path),
            "next_actions": next_actions,
        }

    def _evidence(self, run_id: str) -> dict[str, Any]:
        run_dir = self.root / ".asteria" / "runs" / run_id
        model_calls = self.jsonl.read_all(run_dir / "model_calls.jsonl", "model_call")
        worker_results = self.jsonl.read_all(run_dir / "worker_results.jsonl", "worker_result")
        task_evidence = self.jsonl.read_all(
            run_dir / "task_execution_evidence.jsonl",
            "task_execution_evidence",
        )
        merge_gate = self.jsonl.read_all(run_dir / "merge_gate_evidence.jsonl")
        cost_report = self._read_optional(run_dir / "cost_report.json", "cost_report")
        tiers = sorted({str(call.get("model_tier") or "unknown") for call in model_calls})
        providers_by_tier: dict[str, set[str]] = {}
        purposes_by_tier: dict[str, set[str]] = {}
        for call in model_calls:
            tier = str(call.get("model_tier") or "unknown")
            providers_by_tier.setdefault(tier, set()).add(
                str(call.get("model_provider") or "unknown")
            )
            purposes_by_tier.setdefault(tier, set()).add(str(call.get("purpose") or "unknown"))
        route_evidence = {
            "strong_used": "strong" in tiers,
            "medium_used": "medium" in tiers,
            "tiers": tiers,
            "providers_by_tier": {
                tier: sorted(providers) for tier, providers in sorted(providers_by_tier.items())
            },
            "purposes_by_tier": {
                tier: sorted(purposes) for tier, purposes in sorted(purposes_by_tier.items())
            },
        }
        return {
            "run_dir": str(run_dir),
            "model_call_count": len(model_calls),
            "worker_result_count": len(worker_results),
            "task_execution_evidence_count": len(task_evidence),
            "merge_gate_evidence_count": len(merge_gate),
            "route_evidence": route_evidence,
            "cost_report": cost_report,
            "worker_statuses": sorted(
                {str(result.get("status") or "unknown") for result in worker_results}
            ),
            "execution_statuses": sorted(
                {str(item.get("status") or "unknown") for item in task_evidence}
            ),
        }

    def _status_from_run(self, run_result: RunResult, evidence: dict[str, Any]) -> str:
        route = evidence.get("route_evidence") if isinstance(evidence, dict) else {}
        if (
            isinstance(route, dict)
            and route.get("strong_used")
            and route.get("medium_used")
            and run_result.status not in {"blocked", "paused"}
        ):
            return "completed"
        return "failed"

    def _next_actions(self, status: str, run_id: str, evidence: dict[str, Any]) -> list[str]:
        if status == "completed":
            return [
                f"Inspect `.asteria/gray_runs` summary and run `{run_id}` final report.",
                "Use this run as evidence before widening real-task gray scope.",
            ]
        route = evidence.get("route_evidence") if isinstance(evidence, dict) else {}
        if isinstance(route, dict) and not route.get("medium_used"):
            return ["Worker route did not use medium tier; inspect model routing policy."]
        if isinstance(route, dict) and not route.get("strong_used"):
            return ["Coordinator/planning route did not use strong tier; inspect model routing policy."]
        return [f"Inspect run `{run_id}` blockers, worker results, and final report."]

    def _read_optional(self, path: Path, schema_name: str) -> dict[str, Any]:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _run_result_dict(self, result: RunResult) -> dict[str, Any]:
        return {
            "run_id": result.run_id,
            "status": result.status,
            "final_report_path": str(result.final_report_path),
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "summary": step.summary,
                }
                for step in result.steps
            ],
        }

    def _summary_path(self, gray_run_id: str) -> Path:
        if self.summary_json:
            return self.summary_json.resolve()
        return self.root / ".asteria" / "gray_runs" / gray_run_id / "summary.json"

    def _gray_run_id(self) -> str:
        return "gray-" + now_iso().replace(":", "").replace("+", "-").replace(".", "")
