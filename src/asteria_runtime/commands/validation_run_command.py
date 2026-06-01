from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.run_command import RunCommand, RunResult
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.recovery_pressure import recovery_pressure_report
from asteria_runtime.core.runtime_validation_evidence import (
    record_runtime_validation_matrix_evidence,
)
from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
from asteria_runtime.core.runtime_readiness_gate import runtime_readiness_gate
from asteria_runtime.core.runtime_progress_metrics import runtime_progress_metrics
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


DEFAULT_VALIDATION_GOAL = (
    "Create a tiny local validation artifact named validation_probe.txt containing one line: "
    "validation small task ok. Keep the change minimal and verify the file exists."
)


@dataclass(frozen=True)
class ValidationRunResult:
    validation_run_id: str
    status: str
    summary_path: Path
    run_id: str | None = None
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "control_surface": _validation_run_control_surface(),
            "validation_run_id": self.validation_run_id,
            "status": self.status,
            "summary_path": str(self.summary_path),
            "run_id": self.run_id,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            f"Validation run: {self.validation_run_id}",
            f"Status: {self.status}",
            f"Summary: {self.summary_path}",
        ]
        if self.run_id:
            lines.append(f"Run: {self.run_id}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class ValidationRunCommand:
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
        self.goal = goal or DEFAULT_VALIDATION_GOAL
        self.dry_run = dry_run
        self.max_iterations = max_iterations
        self.max_tasks_per_iteration = max_tasks_per_iteration
        self.validator = SchemaValidator(schema_dir())
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.run_command_factory = run_command_factory or RunCommand
        self.summary_json = summary_json

    def run(self) -> ValidationRunResult:
        validation_run_id = self._validation_run_id()
        summary_path = self._summary_path(validation_run_id)
        version = VersionCommand().run().to_dict()
        package = PackageCheckCommand(self.root).run().to_dict()
        doctor = DoctorCommand(self.root).run()
        gate = GateStatusCommand(self.root).run()
        matrix_evidence = (
            {}
            if self.dry_run
            else record_runtime_validation_matrix_evidence(
                root=self.root,
                validator=self.validator,
                source="validation-run-preflight",
            )
        )
        goal_spec_route_plan = CapabilityFeedbackAdvisor(
            self.validator
        ).goal_spec_execution_plan(self.root / ".asteria", self.goal)
        blocked_reasons = self._blocked_reasons(doctor.to_dict(), gate.to_dict())
        if blocked_reasons:
            summary = self._build_summary(
                validation_run_id=validation_run_id,
                status="blocked",
                summary_path=summary_path,
                version=version,
                package=package,
                doctor=doctor.to_dict(),
                gate=gate.to_dict(),
                goal_spec_route_plan=goal_spec_route_plan,
                run_result=None,
                evidence=self._preflight_evidence(matrix_evidence),
                next_actions=blocked_reasons,
            )
            self.store.write(summary_path, summary, "validation_run")
            return ValidationRunResult(validation_run_id, "blocked", summary_path, None, blocked_reasons)

        if self.dry_run:
            actions = ["Run without `--dry-run` to start the controlled small real-task validation run."]
            summary = self._build_summary(
                validation_run_id=validation_run_id,
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
            self.store.write(summary_path, summary, "validation_run")
            return ValidationRunResult(validation_run_id, "dry_run", summary_path, None, actions)

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
            validation_run_id=validation_run_id,
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
        self.store.write(summary_path, summary, "validation_run")
        return ValidationRunResult(validation_run_id, status, summary_path, run_result.run_id, actions)

    def _blocked_reasons(self, doctor: dict[str, object], gate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if doctor.get("ok") is not True:
            reasons.append("Fix `asteria doctor` error checks before validation-run.")
        if gate.get("stage") != "ready_for_small_real_task_validation":
            blocking_reason = gate.get("blocking_reason")
            if blocking_reason:
                reasons.append(str(blocking_reason))
            else:
                reasons.append(
                    "Reach `ready_for_small_real_task_validation` via real model gate, validation suite, and core acceptance."
                )
        route_guidance = gate.get("route_guidance")
        if isinstance(route_guidance, dict) and route_guidance.get("status") == "blocked":
            reasons.extend(str(item) for item in route_guidance.get("recommended_actions", []))
        return reasons

    def _build_summary(
        self,
        *,
        validation_run_id: str,
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
        validation_plan = self._validation_plan()
        if run_result and isinstance(evidence.get("validation_probe_results"), list):
            validation_plan["probe_results"] = evidence["validation_probe_results"]
        return {
            "schema_version": "0.1.0",
            "control_surface": _validation_run_control_surface(),
            "validation_run_id": validation_run_id,
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
                    "validation-run",
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
            "validation_plan": validation_plan,
            "run_id": run_result["run_id"] if run_result else None,
            "run_result": run_result,
            "evidence": evidence,
            "summary_path": str(summary_path),
            "next_actions": next_actions,
        }

    def _evidence(self, run_id: str) -> dict[str, Any]:
        run_dir = self.root / ".asteria" / "runs" / run_id
        validation_probe_results = self._probe_results(run_id)
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
        progress_metrics = runtime_progress_metrics(self.root, self.validator)
        return {
            "run_dir": str(run_dir),
            "model_call_count": len(model_calls),
            "worker_result_count": len(worker_results),
            "task_execution_evidence_count": len(task_evidence),
            "merge_gate_evidence_count": len(merge_gate),
            "route_evidence": route_evidence,
            "runtime_progress_metrics": progress_metrics,
            "runtime_validation_matrix": runtime_validation_matrix(self.root, progress_metrics),
            "recovery_pressure": recovery_pressure_report(self.root, self.validator),
            "cost_report": cost_report,
            "worker_statuses": sorted(
                {str(result.get("status") or "unknown") for result in worker_results}
            ),
            "execution_statuses": sorted(
                {str(item.get("status") or "unknown") for item in task_evidence}
            ),
            "validation_probe_results": validation_probe_results,
        }

    def _validation_plan(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "purpose": "controlled_real_provider_small_task_gray_validation",
            "risk_model": "adaptive_gates_preserve_agent_flexibility",
            "flexibility_policy": {
                "low_risk_exploration": "trace_only",
                "readonly_and_fake_path": "allow_iteration_with_light_evidence",
                "promotion_merge_remote_and_release": "strong_gate",
            },
            "parallel_writes": {
                "real_disjoint_write_workers": "disabled",
                "enablement_flag": "real_disjoint_write_workers",
                "disjoint_write_gate": "prove_block_before_enable",
            },
            "probes": [
                {
                    "id": "parent_selects_subagent",
                    "intent": "Verify the coordinator can select a subagent path for a scoped task.",
                    "expected_evidence": [
                        "agent_loop_decisions.jsonl:next_action=subagent",
                        "workers.jsonl:subagent worker invocation",
                        "worker_results.jsonl:subagent result",
                    ],
                    "gate_policy": "review_if_missing",
                },
                {
                    "id": "readonly_fanout_succeeds",
                    "intent": "Verify readonly child fanout can run without write privileges.",
                    "expected_evidence": [
                        "subagent_child_plans.jsonl:scheduling_strategy=parallel_readonly_fanout",
                        "worker_results.jsonl:readonly child workers succeeded",
                    ],
                    "gate_policy": "review_if_missing",
                },
                {
                    "id": "readonly_write_tool_blocked",
                    "intent": "Verify a readonly child cannot use write tools.",
                    "expected_evidence": [
                        "agent_loop_observations.jsonl:write tool denied for readonly child",
                        "runtime_readiness_gate:subagent_readonly_fanout blocked or reviewed",
                    ],
                    "gate_policy": "strong_block_on_uncontrolled_write",
                },
                {
                    "id": "disjoint_write_gate_blocks_unsafe_fanout",
                    "intent": (
                        "Verify disjoint write fanout remains blocked without candidate workspace, "
                        "merge gate, or clean promotion recovery evidence."
                    ),
                    "expected_evidence": [
                        "runtime_readiness_gate:subagent_disjoint_write_gate blocked",
                        "gate-status:Disjoint write gate summary",
                    ],
                    "gate_policy": "strong_block_before_real_parallel_write_enable",
                },
                {
                    "id": "parent_loop_stops_after_observation",
                    "intent": "Verify the parent loop can stop cleanly after consuming child observations.",
                    "expected_evidence": [
                        "agent_loop_run_summary.json:exit_reason=completed|stop",
                        "agent_loop_observations.jsonl:subagent_result",
                    ],
                    "gate_policy": "review_if_missing",
                },
            ],
        }

    def _probe_results(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.root / ".asteria" / "runs" / run_id
        plan = self._validation_plan()
        decisions = self.jsonl.read_all(run_dir / "agent_loop_decisions.jsonl", "agent_loop_decision")
        workers = self.jsonl.read_all(run_dir / "workers.jsonl", "worker_invocation")
        worker_results = self.jsonl.read_all(run_dir / "worker_results.jsonl", "worker_result")
        child_plans = self.jsonl.read_all(run_dir / "subagent_child_plans.jsonl", "subagent_child_plan")
        observations = self.jsonl.read_all(run_dir / "agent_loop_observations.jsonl", "agent_loop_observation")
        run_summary = self._read_optional(run_dir / "agent_loop_run_summary.json", "agent_loop_run_summary")
        readiness = runtime_readiness_gate(
            root=self.root,
            validator=self.validator,
            model_call_contract={"status": "healthy"},
            context_pressure_summary={"max_context_window_ratio": 0.1},
            latest_observation_plan={},
        )
        readiness_checks = {
            str(check.get("name") or ""): check
            for check in readiness.get("checks", [])
            if isinstance(check, dict)
        }
        return [
            self._evaluate_probe(
                str(probe["id"]),
                str(probe["gate_policy"]),
                decisions=decisions,
                workers=workers,
                worker_results=worker_results,
                child_plans=child_plans,
                observations=observations,
                run_summary=run_summary,
                readiness_checks=readiness_checks,
            )
            for probe in plan["probes"]
        ]

    def _evaluate_probe(
        self,
        probe_id: str,
        gate_policy: str,
        *,
        decisions: list[dict[str, Any]],
        workers: list[dict[str, Any]],
        worker_results: list[dict[str, Any]],
        child_plans: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        run_summary: dict[str, Any],
        readiness_checks: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        status, summary, evidence_refs = self._probe_status(
            probe_id,
            decisions=decisions,
            workers=workers,
            worker_results=worker_results,
            child_plans=child_plans,
            observations=observations,
            run_summary=run_summary,
            readiness_checks=readiness_checks,
        )
        return {
            "id": probe_id,
            "status": status,
            "summary": summary,
            "gate_policy": gate_policy,
            "evidence_refs": evidence_refs,
        }

    def _probe_status(
        self,
        probe_id: str,
        *,
        decisions: list[dict[str, Any]],
        workers: list[dict[str, Any]],
        worker_results: list[dict[str, Any]],
        child_plans: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        run_summary: dict[str, Any],
        readiness_checks: dict[str, dict[str, Any]],
    ) -> tuple[str, str, list[str]]:
        if probe_id == "parent_selects_subagent":
            has_decision = any(
                _nested_str(item, ["next_action", "action"]) == "subagent" for item in decisions
            )
            worker_ids = [
                str(item.get("worker_invocation_id") or "")
                for item in workers
                if "subagent" in str(item.get("worker_kind") or item.get("agent_id") or "").lower()
            ]
            result_ids = [
                str(item.get("worker_result_id") or "")
                for item in worker_results
                if str(item.get("worker_invocation_id") or "") in worker_ids
                or "subagent" in str(item.get("summary") or "").lower()
            ]
            if has_decision and worker_ids and result_ids:
                return "passed", "Subagent decision, worker, and result evidence are present.", [*worker_ids[:2], *result_ids[:2]]
            return "missing_evidence", "Subagent path was not fully evidenced in this run.", [*worker_ids[:2], *result_ids[:2]]
        if probe_id == "readonly_fanout_succeeds":
            plan_ids = [
                str(item.get("subagent_child_plan_id") or "")
                for item in child_plans
                if str(item.get("scheduling_strategy") or "") == "parallel_readonly_fanout"
            ]
            fanout = readiness_checks.get("subagent_readonly_fanout", {})
            if plan_ids and fanout.get("status") == "ready":
                return "passed", str(fanout.get("summary") or "Readonly fanout succeeded."), plan_ids[:3]
            return "missing_evidence", str(fanout.get("summary") or "Readonly fanout evidence was not present."), plan_ids[:3]
        if probe_id == "readonly_write_tool_blocked":
            denied = [
                str(item.get("observation_id") or item.get("execution_id") or "")
                for item in observations
                if "readonly" in str(item).lower()
                and "write" in str(item).lower()
                and ("denied" in str(item).lower() or "cannot use write tool" in str(item).lower())
            ]
            fanout = readiness_checks.get("subagent_readonly_fanout", {})
            if denied or fanout.get("status") in {"blocked", "review"}:
                return "passed", "Readonly write attempt was blocked or reviewed.", denied[:3]
            return "missing_evidence", "No readonly write-tool denial evidence was found.", []
        if probe_id == "disjoint_write_gate_blocks_unsafe_fanout":
            has_disjoint_plan = any(
                str(item.get("scheduling_strategy") or "")
                == "parallel_disjoint_writes_after_merge_gate"
                or str(item.get("parallel_safety") or "") == "disjoint_writes"
                for item in child_plans
            )
            disjoint = readiness_checks.get("subagent_disjoint_write_gate", {})
            refs = [str(item) for item in disjoint.get("evidence_refs") or []][:4]
            if not has_disjoint_plan:
                return "missing_evidence", str(disjoint.get("summary") or "No disjoint write fanout evidence was found."), refs
            if disjoint.get("status") == "blocked":
                return "passed", str(disjoint.get("summary") or "Disjoint write gate blocked."), refs
            if disjoint.get("status") == "ready":
                return "failed", str(disjoint.get("summary") or "Disjoint write gate did not block unsafe fanout."), refs
            return "missing_evidence", str(disjoint.get("summary") or "No disjoint write fanout evidence was found."), refs
        if probe_id == "parent_loop_stops_after_observation":
            exit_reason = str(run_summary.get("exit_reason") or "")
            has_subagent_observation = any("subagent" in str(item).lower() for item in observations)
            if exit_reason in {"completed", "stop"} and has_subagent_observation:
                return "passed", f"Parent loop stopped with exit_reason={exit_reason}.", [str(run_summary.get("run_id") or "")]
            return "missing_evidence", "Parent loop stop after subagent observation was not fully evidenced.", [str(run_summary.get("run_id") or "")]
        return "missing_evidence", "Probe evaluator is not implemented for this probe.", []

    def _preflight_evidence(self, matrix_evidence: dict[str, Any]) -> dict[str, Any]:
        progress_metrics = runtime_progress_metrics(self.root, self.validator)
        evidence = {
            "runtime_progress_metrics": progress_metrics,
            "runtime_validation_matrix": runtime_validation_matrix(self.root, progress_metrics),
            "recovery_pressure": recovery_pressure_report(self.root, self.validator),
        }
        if matrix_evidence:
            evidence["runtime_validation_matrix_evidence"] = matrix_evidence
        return evidence

    def _status_from_run(self, run_result: RunResult, evidence: dict[str, Any]) -> str:
        route = evidence.get("route_evidence") if isinstance(evidence, dict) else {}
        if (
            isinstance(route, dict)
            and route.get("strong_used")
            and route.get("medium_used")
            and run_result.status not in {"blocked", "paused"}
        ):
            failed_probes = [
                item
                for item in evidence.get("validation_probe_results", [])
                if isinstance(item, dict) and item.get("status") == "failed"
            ]
            if failed_probes:
                return "failed"
            return "completed"
        return "failed"

    def _next_actions(self, status: str, run_id: str, evidence: dict[str, Any]) -> list[str]:
        if status == "completed":
            actions = [
                f"Inspect `.asteria/validation_runs` summary and run `{run_id}` final report.",
                "Use this run as evidence before widening real-task validation scope.",
            ]
            missing = [
                str(item.get("id") or "")
                for item in evidence.get("validation_probe_results", [])
                if isinstance(item, dict) and item.get("status") == "missing_evidence"
            ]
            if missing:
                actions.append(
                    "Review missing validation probe evidence before widening scope: "
                    + ", ".join(item for item in missing if item)
                )
            return actions
        failed = [
            str(item.get("id") or "")
            for item in evidence.get("validation_probe_results", [])
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        if failed:
            return [
                "Repair failed validation probe before widening scope: "
                + ", ".join(item for item in failed if item)
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

    def _summary_path(self, validation_run_id: str) -> Path:
        if self.summary_json:
            return self.summary_json.resolve()
        return self.root / ".asteria" / "validation_runs" / validation_run_id / "summary.json"

    def _validation_run_id(self) -> str:
        timestamp = now_iso().replace(":", "").replace("+", "-").replace(".", "")
        return f"validation-{timestamp}-{uuid4().hex[:8]}"


def _validation_run_control_surface() -> dict[str, object]:
    return control_surface_contract(
        command="validation-run",
        audience="maintainer_validation_execution",
        stable_fields=[
            "schema_version",
            "validation_run_id",
            "status",
            "summary_path",
            "run_id",
            "next_actions",
        ],
    )


def _nested_str(item: dict[str, Any], path: list[str]) -> str:
    current: Any = item
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")
