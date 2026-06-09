from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.run_command import RunCommand, RunResult
from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.recovery_pressure import recovery_pressure_report
from asteria_runtime.core.runtime_validation_evidence import (
    record_runtime_validation_matrix_evidence,
)
from asteria_runtime.core.runtime_validation_matrix import runtime_validation_matrix
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
VALIDATION_PROBE_GOALS = {
    "parent_selects_subagent": (
        "Create a tiny validation artifact named subagent_probe.txt containing one line: "
        "subagent probe ok. This is a validation probe: the parent agent loop must choose "
        "next_action.action=subagent, dispatch a child worker, consume the subagent_result "
        "observation, and stop cleanly after verification."
    ),
    "readonly_fanout_succeeds": (
        "Run a readonly fanout validation probe. The parent agent loop must choose "
        "next_action.action=subagent and request readonly_fanout scheduling so child workers "
        "inspect the repository without write privileges. Record the final aggregate result in "
        "readonly_fanout_probe.txt with one line: readonly fanout probe ok."
    ),
    "readonly_write_tool_blocked": (
        "Run a readonly child-worker write-gate validation probe. The parent agent loop must "
        "choose next_action.action=subagent and request readonly_fanout scheduling; one child "
        "must attempt or propose a write action that the runtime blocks or reviews. Record the "
        "final aggregate result in readonly_write_gate_probe.txt with one line: readonly write "
        "gate probe ok."
    ),
    "disjoint_write_gate_blocks_unsafe_fanout": (
        "Run a disjoint-write safety validation probe. The parent agent loop must choose "
        "next_action.action=subagent and propose disjoint_write_workers scheduling for two "
        "independent file writes, but real parallel disjoint write workers must stay disabled "
        "unless candidate workspace, merge gate, and promotion recovery evidence are present. "
        "Record the blocked-or-reviewed result in disjoint_write_gate_probe.txt with one line: "
        "disjoint write gate probe ok."
    ),
    "parent_loop_stops_after_observation": (
        "Create parent_loop_stop_probe.txt containing one line: parent loop stop probe ok. "
        "The parent loop should consume the child observation and stop cleanly."
    ),
    "repair_replan_path": (
        "Run a scoped validation scenario that intentionally exercises recovery. The runtime "
        "must produce AgentLoopDecision and AgentLoopExecutionResult evidence for repair or "
        "replan after a bounded failure, then stop with a clear recovery observation. Do not use "
        "a tiny file artifact as the primary proof."
    ),
    "ask_stop_path": (
        "Run a scoped validation scenario that reaches a runtime-owned ask or explicit stop. "
        "The runtime must create decision-point or stop-report evidence instead of guessing past "
        "an ambiguous or policy-sensitive boundary. Do not use a tiny file artifact as the "
        "primary proof."
    ),
    "context_pressure_path": (
        "Run a scoped validation scenario that creates explainable context pressure. The runtime "
        "must record context_budget_snapshots.jsonl with a recommended or required compact "
        "boundary, or a completed compaction count. Do not use a tiny file artifact as the "
        "primary proof."
    ),
    "capability_selection_path": (
        "Run a scoped validation scenario that requires choosing among tool, Skill, MCP, or "
        "subagent capabilities. The runtime must record capability decision reasons and selected "
        "capability evidence that can be reconciled with the catalog. Do not use a tiny file "
        "artifact as the primary proof."
    ),
}
FIRST_BATCH_PROBE_IDS = [
    "parent_selects_subagent",
    "readonly_fanout_succeeds",
    "readonly_write_tool_blocked",
    "disjoint_write_gate_blocks_unsafe_fanout",
    "parent_loop_stops_after_observation",
]
SECOND_BATCH_PROBE_IDS = [
    "repair_replan_path",
    "ask_stop_path",
    "context_pressure_path",
    "capability_selection_path",
]


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
        probe_ids: list[str] | None = None,
        run_command_factory: Callable[..., RunCommand] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.probe_ids = _normalize_probe_ids(probe_ids)
        self.goal = goal or _goal_for_probe_ids(self.probe_ids) or DEFAULT_VALIDATION_GOAL
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
        goal_spec_route_plan = CapabilityFeedbackAdvisor(self.validator).goal_spec_execution_plan(
            self.root / ".asteria", self.goal
        )
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
            return ValidationRunResult(
                validation_run_id, "blocked", summary_path, None, blocked_reasons
            )

        if self.dry_run:
            actions = [
                "Run without `--dry-run` to start the controlled small real-task validation run."
            ]
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

        multi_runtime_probe_actions = self._multiple_runtime_managed_probe_actions()
        if multi_runtime_probe_actions:
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
                next_actions=multi_runtime_probe_actions,
            )
            self.store.write(summary_path, summary, "validation_run")
            return ValidationRunResult(
                validation_run_id,
                "blocked",
                summary_path,
                None,
                multi_runtime_probe_actions,
            )

        run_command = self.run_command_factory(
            root=self.root,
            goal=self.goal,
            max_iterations=self._effective_max_iterations(),
            max_tasks_per_iteration=self.max_tasks_per_iteration,
            enable_research=False,
            parallel_writes=False,
            validation_probe_ids=self.probe_ids,
        )
        try:
            run_result = run_command.run()
        except Exception as exc:
            evidence = self._failed_execution_evidence(exc, matrix_evidence)
            actions = self._failed_execution_next_actions(evidence)
            summary = self._build_summary(
                validation_run_id=validation_run_id,
                status="failed",
                summary_path=summary_path,
                version=version,
                package=package,
                doctor=doctor.to_dict(),
                gate=gate.to_dict(),
                goal_spec_route_plan=goal_spec_route_plan,
                run_result=None,
                evidence=evidence,
                next_actions=actions,
            )
            self.store.write(summary_path, summary, "validation_run")
            return ValidationRunResult(validation_run_id, "failed", summary_path, None, actions)
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
        return ValidationRunResult(
            validation_run_id, status, summary_path, run_result.run_id, actions
        )

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

    def _failed_execution_evidence(
        self,
        exc: Exception,
        matrix_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        latest_failure_path = self.root / ".asteria" / "model" / "latest_failure.json"
        latest_failure = _read_json_file(latest_failure_path)
        failure_type = "runtime_execution_error"
        if isinstance(latest_failure, dict):
            failure_type = str(latest_failure.get("failure_type") or failure_type)
        return {
            "execution_failure": {
                "error_type": type(exc).__name__,
                "failure_type": failure_type,
                "summary": str(exc),
                "latest_failure_path": str(latest_failure_path)
                if latest_failure_path.exists()
                else None,
                "latest_failure": latest_failure if isinstance(latest_failure, dict) else None,
            },
            "runtime_validation_matrix_evidence": matrix_evidence,
            "runtime_progress_metrics": runtime_progress_metrics(self.root, self.validator),
            "recovery_pressure": recovery_pressure_report(self.root, self.validator),
        }

    def _failed_execution_next_actions(self, evidence: dict[str, Any]) -> list[str]:
        failure = evidence.get("execution_failure")
        failure = failure if isinstance(failure, dict) else {}
        latest_failure = failure.get("latest_failure")
        latest_failure = latest_failure if isinstance(latest_failure, dict) else {}
        recommendations = [
            str(item) for item in latest_failure.get("recommendations") or [] if item
        ]
        if recommendations:
            return recommendations
        failure_type = str(failure.get("failure_type") or "")
        if failure_type in {"network", "timeout", "rate_limited", "server_error"}:
            return [
                "Refresh provider route health, then rerun the targeted validation probe.",
            ]
        return ["Inspect validation-run execution_failure evidence before rerunning."]

    def _effective_max_iterations(self) -> int:
        single_iteration_probe_ids = {
            "readonly_write_tool_blocked",
            "disjoint_write_gate_blocks_unsafe_fanout",
            "repair_replan_path",
            "ask_stop_path",
            "context_pressure_path",
            "capability_selection_path",
        }
        if single_iteration_probe_ids & set(self.probe_ids):
            return min(self.max_iterations, 1)
        return self.max_iterations

    def _multiple_runtime_managed_probe_actions(self) -> list[str]:
        selected = [probe_id for probe_id in self.probe_ids if probe_id in SECOND_BATCH_PROBE_IDS]
        if len(selected) <= 1:
            return []
        commands = ", ".join(_probe_command(probe_id) for probe_id in selected)
        return [
            (
                "Run one second-batch runtime-managed validation probe per validation-run "
                "command so each probe can own its task contract and stop boundary."
            ),
            f"Suggested probe commands: {commands}",
        ]

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
        if run_result and isinstance(evidence.get("recommended_probe_runs"), list):
            validation_plan["recommended_probe_runs"] = evidence["recommended_probe_runs"]
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
        studio_benchmark = self._studio_runtime_progress_benchmark(run_id)
        return {
            "run_dir": str(run_dir),
            "model_call_count": len(model_calls),
            "worker_result_count": len(worker_results),
            "task_execution_evidence_count": len(task_evidence),
            "merge_gate_evidence_count": len(merge_gate),
            "route_evidence": route_evidence,
            "runtime_progress_metrics": progress_metrics,
            "studio_runtime_progress_benchmark": studio_benchmark,
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
            "selected_probe_ids": self.probe_ids,
            "next_probe_goals": self._next_probe_goals(self.probe_ids),
            "second_batch_probe_goals": self._next_probe_goals(SECOND_BATCH_PROBE_IDS),
            "recommended_scoped_validation_batch": {
                "status": "ready_after_dogfooding_gate",
                "sample_shape": "repair_replan_ask_stop_context_pressure_capability_selection",
                "probe_ids": SECOND_BATCH_PROBE_IDS,
                "avoid": "do_not_repeat_tiny_file_artifact_as_primary_proof",
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
                        "subagent_child_plans.jsonl:scheduling_strategy=parallel_readonly_safe",
                        "worker_results.jsonl:readonly child workers succeeded",
                    ],
                    "gate_policy": "review_if_missing",
                },
                {
                    "id": "readonly_write_tool_blocked",
                    "intent": "Verify a readonly child cannot use write tools.",
                    "expected_evidence": [
                        "agent_loop_observations.jsonl:write tool denied for readonly child",
                        "agent_loop_observations.jsonl:readonly write tool denied",
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
                        "subagent_child_plans.jsonl:unsafe disjoint write plan rejected",
                        "merge_gate_evidence.jsonl:write boundary blocked",
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
                {
                    "id": "repair_replan_path",
                    "intent": "Verify bounded failures enter repair or replan evidence paths.",
                    "expected_evidence": [
                        "agent_loop_decisions.jsonl:next_action=repair|replan",
                        "agent_loop_execution_results.jsonl:action=repair|replan",
                        "agent_loop_observations.jsonl:repair/replan observation",
                    ],
                    "gate_policy": "strong_block_if_targeted_missing",
                },
                {
                    "id": "ask_stop_path",
                    "intent": "Verify ambiguous or policy-sensitive work stops at ask/stop evidence.",
                    "expected_evidence": [
                        "agent_loop_decisions.jsonl:next_action=ask|stop",
                        "agent_loop_execution_results.jsonl:target=decision_point|stop_report",
                        "agent_loop_run_summary.json:exit_reason=ask|stop",
                    ],
                    "gate_policy": "strong_block_if_targeted_missing",
                },
                {
                    "id": "context_pressure_path",
                    "intent": "Verify context pressure produces compact-boundary evidence.",
                    "expected_evidence": [
                        "context_budget_snapshots.jsonl:compact_boundary=recommended|required",
                        "cost_report.json:context_compactions>0",
                    ],
                    "gate_policy": "review_if_missing",
                },
                {
                    "id": "capability_selection_path",
                    "intent": "Verify capability selection records reasoned catalog-aligned choices.",
                    "expected_evidence": [
                        "capability_decisions.jsonl:decision.reason",
                        "mcp_invocations.jsonl|skill_invocations.jsonl:capability_decision.reason",
                        "user_progress.jsonl:capability_type=mcp|skill",
                    ],
                    "gate_policy": "review_if_missing",
                },
            ],
        }

    def _probe_results(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.root / ".asteria" / "runs" / run_id
        plan = self._validation_plan()
        decisions = self.jsonl.read_all(
            run_dir / "agent_loop_decisions.jsonl", "agent_loop_decision"
        )
        workers = self.jsonl.read_all(run_dir / "workers.jsonl", "worker_invocation")
        worker_results = self.jsonl.read_all(run_dir / "worker_results.jsonl", "worker_result")
        child_plans = self.jsonl.read_all(
            run_dir / "subagent_child_plans.jsonl", "subagent_child_plan"
        )
        observations = self.jsonl.read_all(
            run_dir / "agent_loop_observations.jsonl", "agent_loop_observation"
        )
        execution_results = self.jsonl.read_all(
            run_dir / "agent_loop_execution_results.jsonl", "agent_loop_execution_result"
        )
        runtime_requests = self.jsonl.read_all(run_dir / "runtime_requests.jsonl", "runtime_request")
        decision_points = self.jsonl.read_all(run_dir / "decisions.jsonl", "decision_point")
        context_snapshots = self.jsonl.read_all(
            run_dir / "context_budget_snapshots.jsonl", "context_budget_snapshot"
        )
        run_summary = self._read_optional(
            run_dir / "agent_loop_run_summary.json", "agent_loop_run_summary"
        )
        cost_report = self._read_optional(run_dir / "cost_report.json", "cost_report")
        progress_metrics = runtime_progress_metrics(self.root, self.validator)
        return [
            self._evaluate_probe(
                str(probe["id"]),
                str(probe["gate_policy"]),
                decisions=decisions,
                workers=workers,
                worker_results=worker_results,
                child_plans=child_plans,
                observations=observations,
                execution_results=execution_results,
                runtime_requests=runtime_requests,
                decision_points=decision_points,
                context_snapshots=context_snapshots,
                run_summary=run_summary,
                cost_report=cost_report,
                progress_metrics=progress_metrics,
            )
            for probe in plan["probes"]
        ]

    def _next_probe_goals(self, probe_ids: list[str]) -> list[dict[str, Any]]:
        selected = probe_ids or FIRST_BATCH_PROBE_IDS
        return [
            {
                "probe_id": probe_id,
                "goal": VALIDATION_PROBE_GOALS[probe_id],
                "command": _probe_command(probe_id),
            }
            for probe_id in selected
            if probe_id in VALIDATION_PROBE_GOALS
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
        execution_results: list[dict[str, Any]],
        runtime_requests: list[dict[str, Any]],
        decision_points: list[dict[str, Any]],
        context_snapshots: list[dict[str, Any]],
        run_summary: dict[str, Any],
        cost_report: dict[str, Any],
        progress_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        status, summary, evidence_refs = self._probe_status(
            probe_id,
            decisions=decisions,
            workers=workers,
            worker_results=worker_results,
            child_plans=child_plans,
            observations=observations,
            execution_results=execution_results,
            runtime_requests=runtime_requests,
            decision_points=decision_points,
            context_snapshots=context_snapshots,
            run_summary=run_summary,
            cost_report=cost_report,
            progress_metrics=progress_metrics,
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
        execution_results: list[dict[str, Any]] | None = None,
        runtime_requests: list[dict[str, Any]] | None = None,
        decision_points: list[dict[str, Any]] | None = None,
        context_snapshots: list[dict[str, Any]] | None = None,
        run_summary: dict[str, Any] | None = None,
        cost_report: dict[str, Any] | None = None,
        progress_metrics: dict[str, Any] | None = None,
    ) -> tuple[str, str, list[str]]:
        execution_results = execution_results or []
        runtime_requests = runtime_requests or []
        decision_points = decision_points or []
        context_snapshots = context_snapshots or []
        run_summary = run_summary or {}
        cost_report = cost_report or {}
        progress_metrics = progress_metrics or {}
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
                return (
                    "passed",
                    "Subagent decision, worker, and result evidence are present.",
                    [*worker_ids[:2], *result_ids[:2]],
                )
            return (
                "missing_evidence",
                "Subagent path was not fully evidenced in this run.",
                [*worker_ids[:2], *result_ids[:2]],
            )
        if probe_id == "readonly_fanout_succeeds":
            readonly_plans = [item for item in child_plans if _is_readonly_fanout_strategy(item)]
            plan_ids = [str(item.get("subagent_child_plan_id") or "") for item in readonly_plans]
            expected_task_ids = {
                str(child.get("child_task_id") or child.get("task_id") or "")
                for plan in readonly_plans
                for child in plan.get("child_tasks") or []
                if isinstance(child, dict)
            }
            readonly_workers = [
                item
                for item in workers
                if str(item.get("task_id") or "") in expected_task_ids
                and str(item.get("parallel_safety") or "") == "readonly"
            ]
            worker_ids = {
                str(item.get("worker_invocation_id") or "") for item in readonly_workers
            }
            succeeded_worker_ids = {
                str(item.get("worker_invocation_id") or "")
                for item in worker_results
                if str(item.get("status") or "") == "succeeded"
            }
            if expected_task_ids and len(readonly_workers) == len(expected_task_ids) and worker_ids <= succeeded_worker_ids:
                return (
                    "passed",
                    "Readonly fanout child workers completed inside the readonly boundary.",
                    [*plan_ids[:2], *sorted(worker_ids)[:2]],
                )
            return (
                "missing_evidence",
                "Readonly fanout does not have matching successful readonly child workers.",
                plan_ids[:3],
            )
        if probe_id == "readonly_write_tool_blocked":
            denied = [
                str(item.get("observation_id") or item.get("execution_id") or "")
                for item in observations
                if "readonly" in str(item).lower()
                and "write" in str(item).lower()
                and ("denied" in str(item).lower() or "cannot use write tool" in str(item).lower())
            ]
            if denied:
                return "passed", "Readonly write attempt was denied at the action boundary.", denied[:3]
            return "missing_evidence", "No readonly write-tool denial evidence was found.", []
        if probe_id == "disjoint_write_gate_blocks_unsafe_fanout":
            has_disjoint_plan = any(
                str(item.get("scheduling_strategy") or "")
                == "parallel_disjoint_writes_after_merge_gate"
                or str(item.get("parallel_safety") or "") == "disjoint_writes"
                for item in child_plans
            )
            blocked = [
                str(item.get("observation_id") or item.get("execution_id") or "")
                for item in [*observations, *execution_results]
                if "disjoint" in str(item).lower()
                and ("blocked" in str(item).lower() or "denied" in str(item).lower())
            ]
            if not has_disjoint_plan:
                return (
                    "missing_evidence",
                    "No disjoint write fanout evidence was found.",
                    [],
                )
            if blocked:
                return (
                    "passed",
                    "Unsafe disjoint write fanout was denied at the action boundary.",
                    blocked[:4],
                )
            return (
                "missing_evidence",
                "Disjoint write plan exists, but no action-boundary denial evidence was recorded.",
                [],
            )
        if probe_id == "parent_loop_stops_after_observation":
            exit_reason = str(run_summary.get("exit_reason") or "")
            has_subagent_observation = any("subagent" in str(item).lower() for item in observations)
            if exit_reason in {"completed", "stop"} and has_subagent_observation:
                return (
                    "passed",
                    f"Parent loop stopped with exit_reason={exit_reason}.",
                    [str(run_summary.get("run_id") or "")],
                )
            return (
                "missing_evidence",
                "Parent loop stop after subagent observation was not fully evidenced.",
                [str(run_summary.get("run_id") or "")],
            )
        if probe_id == "repair_replan_path":
            refs = _action_refs(decisions, execution_results, {"repair", "replan"})
            observed = any(
                "repair" in str(item).lower() or "replan" in str(item).lower()
                for item in observations
            )
            if refs and observed:
                return (
                    "passed",
                    "Repair or replan path produced decision, execution, and observation evidence.",
                    refs[:4],
                )
            return (
                "missing_evidence",
                "No complete repair/replan decision-execution-observation path was found.",
                refs[:4],
            )
        if probe_id == "ask_stop_path":
            refs = _action_refs(decisions, execution_results, {"ask", "stop"})
            exit_reason = str(run_summary.get("exit_reason") or "")
            has_terminal_boundary = exit_reason in {"ask", "stop"} or any(
                str(item.get("target") or "") in {"decision_point", "stop_report"}
                for item in execution_results
            )
            runtime_request_refs = _runtime_request_decision_refs(
                runtime_requests, decision_points
            )
            if runtime_request_refs:
                return (
                    "passed",
                    "Ask/stop boundary produced runtime request and DecisionPoint evidence.",
                    runtime_request_refs[:4],
                )
            if refs and has_terminal_boundary:
                return (
                    "passed",
                    f"Ask/stop boundary was evidenced with exit_reason={exit_reason or 'n/a'}.",
                    refs[:4],
                )
            return (
                "missing_evidence",
                "No ask/stop DecisionPoint or stop-report boundary evidence was found.",
                refs[:4],
            )
        if probe_id == "context_pressure_path":
            pressure_refs = [
                str(item.get("snapshot_id") or "")
                for item in context_snapshots
                if _compact_boundary_status(item) in {"dedupe_recommended", "recommended", "required"}
                or str(item.get("pressure_status") or "") in {"near_limit", "hard_stop", "exceeded"}
            ]
            compactions = int(cost_report.get("context_compactions") or 0)
            if pressure_refs or compactions > 0:
                return (
                    "passed",
                    "Context pressure or compaction evidence was recorded.",
                    pressure_refs[:4],
                )
            return (
                "missing_evidence",
                "No context pressure compact-boundary or compaction evidence was found.",
                [],
            )
        if probe_id == "capability_selection_path":
            adapter = progress_metrics.get("adapter_invocation_coverage")
            adapter = adapter if isinstance(adapter, dict) else {}
            permission = progress_metrics.get("permission_reason_coverage")
            permission = permission if isinstance(permission, dict) else {}
            has_reason = int(permission.get("with_reason") or 0) > 0
            has_adapter_reason = (
                int(adapter.get("mcp_with_reason") or 0) > 0
                or int(adapter.get("skill_with_reason") or 0) > 0
            )
            has_progress_event = int(adapter.get("capability_progress_event_count") or 0) > 0
            if has_reason and has_adapter_reason and has_progress_event:
                return (
                    "passed",
                    "Capability choices include decision reasons, adapter evidence, and progress events.",
                    ["capability_decisions.jsonl", "mcp_invocations.jsonl", "skill_invocations.jsonl"],
                )
            return (
                "missing_evidence",
                "Capability selection evidence lacks reasoned decision, adapter, or progress coverage.",
                [],
            )
        return "missing_evidence", "Probe evaluator is not implemented for this probe.", []

    def _preflight_evidence(self, matrix_evidence: dict[str, Any]) -> dict[str, Any]:
        progress_metrics = runtime_progress_metrics(self.root, self.validator)
        evidence = {
            "runtime_progress_metrics": progress_metrics,
            "runtime_validation_matrix": runtime_validation_matrix(self.root, progress_metrics),
            "recovery_pressure": recovery_pressure_report(self.root, self.validator),
            "recommended_probe_runs": self._next_probe_goals([]),
        }
        if matrix_evidence:
            evidence["runtime_validation_matrix_evidence"] = matrix_evidence
        return evidence

    def _status_from_run(self, run_result: RunResult, evidence: dict[str, Any]) -> str:
        route = evidence.get("route_evidence") if isinstance(evidence, dict) else {}
        if (
            isinstance(route, dict)
            and route.get("strong_used")
            and (route.get("medium_used") or self.probe_ids)
            and (run_result.status not in {"blocked", "paused"} or self.probe_ids)
        ):
            studio_benchmark = evidence.get("studio_runtime_progress_benchmark")
            if isinstance(studio_benchmark, dict) and studio_benchmark.get("ok") is False:
                return "failed"
            failed_probes = [
                item
                for item in evidence.get("validation_probe_results", [])
                if isinstance(item, dict) and item.get("status") == "failed"
            ]
            if failed_probes:
                return "failed"
            missing_targeted_probes = [
                item
                for item in evidence.get("validation_probe_results", [])
                if isinstance(item, dict)
                and item.get("status") == "missing_evidence"
                and item.get("id") in set(self.probe_ids)
            ]
            if missing_targeted_probes:
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
                recommended = [
                    item
                    for item in self._next_probe_goals(missing)
                    if item.get("probe_id") in set(missing)
                ]
                evidence["recommended_probe_runs"] = recommended
                actions.append(
                    "Review missing validation probe evidence before widening scope: "
                    + ", ".join(item for item in missing if item)
                )
                if recommended:
                    actions.append(
                        "Run targeted validation probe: " + str(recommended[0].get("command"))
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
        studio_benchmark = evidence.get("studio_runtime_progress_benchmark")
        if isinstance(studio_benchmark, dict) and studio_benchmark.get("ok") is False:
            failed_checks = [
                str(check.get("name") or "")
                for check in studio_benchmark.get("checks", [])
                if isinstance(check, dict) and check.get("ok") is False
            ]
            return [
                "Fix Studio runtime progress contract before widening scope: "
                + ", ".join(item for item in failed_checks if item),
                f"Run `asteria studio-benchmark --run-id {run_id} --json` after the repair.",
            ]
        missing_targeted = [
            str(item.get("id") or "")
            for item in evidence.get("validation_probe_results", [])
            if isinstance(item, dict)
            and item.get("status") == "missing_evidence"
            and item.get("id") in set(self.probe_ids)
        ]
        if missing_targeted:
            return [
                "Targeted validation probe did not produce required evidence: "
                + ", ".join(item for item in missing_targeted if item),
                "Tighten planner/subagent scheduling before counting this probe as closed.",
            ]
        route = evidence.get("route_evidence") if isinstance(evidence, dict) else {}
        if isinstance(route, dict) and not route.get("medium_used") and not self.probe_ids:
            return ["Worker route did not use medium tier; inspect model routing policy."]
        if isinstance(route, dict) and not route.get("strong_used"):
            return [
                "Coordinator/planning route did not use strong tier; inspect model routing policy."
            ]
        return [f"Inspect run `{run_id}` blockers, worker results, and final report."]

    def _studio_runtime_progress_benchmark(self, run_id: str) -> dict[str, Any]:
        manifest = self._studio_benchmark_manifest()
        result = StudioBenchmarkCommand(
            root=self.root,
            manifest=manifest,
            run_id=run_id,
        ).run()
        payload = result.to_dict()
        payload["manifest_path"] = str(manifest)
        return payload

    def _studio_benchmark_manifest(self) -> Path:
        workspace_manifest = self.root / "benchmarks" / "studio_user_tasks.json"
        if workspace_manifest.exists():
            return workspace_manifest
        return Path(__file__).resolve().parents[3] / "benchmarks" / "studio_user_tasks.json"

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


def _normalize_probe_ids(probe_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for probe_id in probe_ids or []:
        if probe_id in VALIDATION_PROBE_GOALS and probe_id not in normalized:
            normalized.append(probe_id)
    return normalized


def _goal_for_probe_ids(probe_ids: list[str]) -> str:
    if not probe_ids:
        return ""
    if len(probe_ids) == 1:
        return VALIDATION_PROBE_GOALS.get(probe_ids[0], "")
    goals = [
        VALIDATION_PROBE_GOALS[probe_id]
        for probe_id in probe_ids
        if probe_id in VALIDATION_PROBE_GOALS
    ]
    if not goals:
        return ""
    return "Run a controlled validation batch for these missing probe targets. " + " ".join(goals)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _probe_command(probe_id: str) -> str:
    goal = VALIDATION_PROBE_GOALS.get(probe_id, DEFAULT_VALIDATION_GOAL)
    escaped = goal.replace('"', '\\"')
    return f'python -m asteria_runtime validation-run "{escaped}" --probe-id {probe_id} --root . --json'


def _is_readonly_fanout_strategy(item: dict[str, Any]) -> bool:
    return str(item.get("scheduling_strategy") or "") in {
        "parallel_readonly_safe",
        "parallel_readonly_fanout",
    }


def _action_refs(
    decisions: list[dict[str, Any]],
    execution_results: list[dict[str, Any]],
    actions: set[str],
) -> list[str]:
    refs = [
        str(item.get("decision_id") or "")
        for item in decisions
        if _nested_str(item, ["next_action", "action"]) in actions
    ]
    refs.extend(
        str(item.get("execution_id") or "")
        for item in execution_results
        if str(item.get("action") or "") in actions
    )
    return [item for item in refs if item]


def _runtime_request_decision_refs(
    runtime_requests: list[dict[str, Any]],
    decision_points: list[dict[str, Any]],
) -> list[str]:
    decision_by_id = {
        str(item.get("decision_id") or ""): item
        for item in decision_points
        if str(item.get("decision_id") or "")
    }
    refs: list[str] = []
    for request in runtime_requests:
        if str(request.get("status") or "") != "decision_created":
            continue
        decision_id = str(request.get("decision_id") or "")
        decision = decision_by_id.get(decision_id)
        if not decision:
            continue
        if str(decision.get("status") or "") not in {"pending", "created"}:
            continue
        refs.append(str(request.get("runtime_request_id") or ""))
        refs.append(decision_id)
    return [item for item in refs if item]


def _compact_boundary_status(snapshot: dict[str, Any]) -> str:
    boundary = snapshot.get("compact_boundary")
    boundary = boundary if isinstance(boundary, dict) else {}
    return str(boundary.get("status") or "")


def _nested_str(item: dict[str, Any], path: list[str]) -> str:
    current: Any = item
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")
