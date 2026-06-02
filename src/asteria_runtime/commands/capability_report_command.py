from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands._runtime_os_helpers import (
    runtime_os_acceptance_evidence,
    runtime_os_catalog_report,
    runtime_os_full_summary,
    runtime_os_release_evidence,
)
from asteria_runtime.core.acceptance_catalog import (
    acceptance_metadata_index,
    enrich_acceptance_report,
    enrich_acceptance_scenario,
)
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.failure_attribution import classify_failure_attribution
from asteria_runtime.core.real_provider_matrix import (
    latest_real_provider_matrix,
    real_provider_matrix_text_lines,
)
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class CapabilityReportResult:
    root: Path
    acceptance_runs: int
    latest_acceptance: dict[str, Any] = field(default_factory=dict)
    capability_summary: dict[str, dict[str, int]] = field(default_factory=dict)
    failure_types: dict[str, int] = field(default_factory=dict)
    average_repair_rounds: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    tool_budget_units: int = 0
    max_context_estimated_tokens: int = 0
    max_context_window_ratio: float = 0.0
    context_sections: dict[str, int] = field(default_factory=dict)
    context_duplicate_content_hashes: list[str] = field(default_factory=list)
    model_profiles: list[dict[str, Any]] = field(default_factory=list)
    model_profile_path: Path | None = None
    route_guidance: dict[str, Any] = field(default_factory=dict)
    latest_real_provider_matrix: dict[str, Any] = field(default_factory=dict)
    matrix_route_guidance: dict[str, Any] = field(default_factory=dict)
    capability_selection: dict[str, Any] = field(default_factory=dict)
    runtime_os: dict[str, Any] = field(default_factory=dict)
    evidence_health: dict[str, Any] = field(default_factory=dict)
    common_blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "Capability report",
            f"Root: {self.root}",
            f"Acceptance runs: {self.acceptance_runs}",
        ]
        if self.latest_acceptance:
            lines.extend(
                [
                    (
                        "Latest acceptance: "
                        f"{'pass' if self.latest_acceptance.get('ok') else 'fail'} "
                        f"suite={self.latest_acceptance.get('suite')} "
                        f"scenarios={self.latest_acceptance.get('passed')}/"
                        f"{self.latest_acceptance.get('total')}"
                    ),
                    "Latest acceptance state: "
                    f"{self.latest_acceptance.get('release_validation')}",
                ]
            )
        if self.evidence_health:
            lines.append(
                "Evidence health: "
                f"{self.evidence_health.get('status')} - "
                f"{self.evidence_health.get('summary')}"
            )
        if self.capability_summary:
            lines.append("Capabilities:")
            for capability, summary in sorted(self.capability_summary.items()):
                lines.append(
                    f"  - {capability}: {summary.get('passed', 0)}/{summary.get('total', 0)} passed"
                )
        if self.failure_types:
            lines.append("Failure types:")
            for failure_type, count in sorted(
                self.failure_types.items(), key=lambda item: (-item[1], item[0])
            )[:8]:
                lines.append(f"  - {failure_type}: {count}")
        lines.append(f"Average repair rounds: {self.average_repair_rounds:.2f}")
        lines.append(
            "Cost signals: "
            f"{self.model_calls} model calls, "
            f"{self.tool_calls} raw tool calls, "
            f"{self.tool_budget_units} weighted tool units, "
            f"{self.max_context_estimated_tokens} max context tokens "
            f"({self.max_context_window_ratio:.2f} window ratio)"
        )
        if self.context_sections:
            top_sections = sorted(
                self.context_sections.items(), key=lambda item: (-item[1], item[0])
            )[:6]
            lines.append(
                "Context sections: "
                + ", ".join(f"{name}={tokens}" for name, tokens in top_sections)
            )
        if self.context_duplicate_content_hashes:
            lines.append(
                "Repeated context hashes: "
                + ", ".join(self.context_duplicate_content_hashes[:6])
            )
        if self.model_profiles:
            lines.append("Model capability profiles:")
            for profile in self.model_profiles[:8]:
                lines.append(
                    "  - "
                    f"{profile['provider']}/{profile['model']} "
                    f"purpose={profile['purpose']} tier={profile['model_tier']}: "
                    f"{profile['success_rate']:.2f} success "
                    f"({profile['success_calls']}/{profile['total_calls']} calls, "
                    f"{profile['input_tokens']} in/{profile['output_tokens']} out tokens, "
                    f"worker={profile.get('worker_success_rate', 0.0):.2f}, "
                    f"validation={profile.get('validation_pass_rate', 0.0):.2f}, "
                    f"runtime_requests={profile.get('runtime_request_total', 0)}, "
                    f"matrix={profile.get('matrix_signal_success_rate', 0.0):.2f}/"
                    f"{profile.get('matrix_signal_total', 0)}, "
                    f"merge_blocks={profile.get('merge_gate_blocks', 0)})"
                )
        if self.model_profile_path:
            lines.append(f"Model profile: {self.model_profile_path}")
        if self.route_guidance:
            lines.append(f"Route guidance: {self.route_guidance.get('status', 'unknown')}")
            for action in self.route_guidance.get("recommended_actions", [])[:3]:
                lines.append(f"  - {action}")
        if self.latest_real_provider_matrix:
            lines.extend(real_provider_matrix_text_lines(self.latest_real_provider_matrix))
        if self.matrix_route_guidance:
            lines.append(
                "Matrix route guidance: "
                f"{self.matrix_route_guidance.get('status', 'unknown')}"
            )
            for action in self.matrix_route_guidance.get("recommended_actions", [])[:3]:
                lines.append(f"  - {action}")
        if self.capability_selection:
            summary = self.capability_selection.get("summary") or {}
            lines.append(
                "Capability selection audit: "
                f"tasks={summary.get('tasks', 0)}, "
                f"visible={summary.get('visible', 0)}, "
                f"selected={summary.get('selected', 0)}, "
                f"skipped={summary.get('skipped', 0)}, "
                f"blocked={summary.get('blocked', 0)}"
            )
            reasons = self.capability_selection.get("reason_counts") or {}
            if reasons:
                top_reasons = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:5]
                lines.append(
                    "  - selection reasons: "
                    + "; ".join(f"{reason} ({count})" for reason, count in top_reasons)
                )
            actual = self.capability_selection.get("actual_selection") or {}
            if actual:
                lines.append(
                    "  - actual decisions: "
                    f"{actual.get('actual_count', 0)} recorded, "
                    f"{len(actual.get('actual_not_selected') or [])} not selected"
                )
                visible = actual.get("actual_visible_not_selected") or []
                missing = actual.get("actual_missing_from_catalog") or []
                if visible:
                    lines.append("    - visible but not selected: " + ", ".join(visible[:5]))
                if missing:
                    lines.append("    - missing from catalog: " + ", ".join(missing[:5]))
        if self.runtime_os:
            label = "Runtime OS release evidence"
            if self.evidence_health.get("status") == "historical_evidence_noise":
                label += " (historical baseline)"
            lines.append(f"{label}:")
            gate = self.runtime_os.get("gate") or {}
            lines.append(f"  - gate: {gate.get('status', 'unknown')}")
            evidence = self.runtime_os.get("evidence") or {}
            lines.append(
                "  - workers: "
                f"{evidence.get('worker_results', 0)} result(s) from "
                f"{evidence.get('worker_invocations', 0)} invocation(s)"
            )
            if evidence.get("acceptance_worker_results_jsonl"):
                lines.append("  - acceptance worker evidence: present")
            lines.append(f"  - task graph selections: {evidence.get('task_graph_selections', 0)}")
            manifest_audit = evidence.get("capability_manifest_audit") or {}
            if manifest_audit:
                lines.append(
                    "  - capability manifest audit: "
                    f"{manifest_audit.get('prompt_envelopes', 0)} envelope(s), "
                    f"{manifest_audit.get('model_calls_with_capability_manifest', 0)} "
                    "model call(s) linked"
                )
                if manifest_audit.get("context_envelopes") is not None:
                    lines.append(
                        "  - context envelope audit: "
                        f"{manifest_audit.get('context_envelopes', 0)} envelope(s), "
                        f"{manifest_audit.get('model_calls_with_context_envelope', 0)} "
                        "model call(s) linked"
                    )
                cache_break_reasons = [
                    str(item) for item in manifest_audit.get("cache_break_reasons", [])
                ]
                if cache_break_reasons:
                    lines.append(
                        "  - cache break reasons: "
                        + ", ".join(cache_break_reasons[:6])
                    )
            missing = gate.get("missing_capabilities") or []
            if missing:
                lines.append("  - missing capabilities: " + ", ".join(missing))
            missing_evidence = gate.get("missing_evidence") or []
            if missing_evidence:
                lines.append("  - missing evidence:")
                lines.extend(f"    - {item}" for item in missing_evidence[:8])
        if self.common_blockers:
            lines.append("Common blockers:")
            lines.extend(f"  - {item}" for item in self.common_blockers[:5])
        if self.next_actions:
            lines.append("Recommended next actions:")
            lines.extend(f"  - {item}" for item in self.next_actions)
        return "\n".join(lines)


class CapabilityReportCommand:
    def __init__(self, root: Path, limit: int = 20) -> None:
        self.root = root.resolve()
        self.limit = limit
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> CapabilityReportResult:
        agent_dir = self.root / ".asteria"
        acceptance_runs = self._acceptance_history(agent_dir)[-self.limit :]
        latest = self._latest_acceptance(agent_dir) or (
            acceptance_runs[-1] if acceptance_runs else {}
        )
        capability_summary = self._capability_summary(acceptance_runs, latest)
        failure_types, blockers, repair_rounds = self._execution_evidence_summary(agent_dir)
        (
            model_calls,
            tool_calls,
            tool_budget_units,
            max_context_estimated_tokens,
            max_context_window_ratio,
            context_sections,
            context_duplicate_content_hashes,
        ) = self._cost_signals(agent_dir)
        model_profiles = self._model_profiles(agent_dir)
        model_profile_path = self._write_model_profile(agent_dir, model_profiles)
        route_guidance = CapabilityFeedbackAdvisor(self.validator).route_guidance(agent_dir)
        route_guidance = self._normalized_route_guidance(latest, route_guidance)
        latest_matrix = latest_real_provider_matrix(agent_dir)
        matrix_route_guidance = self._matrix_route_guidance(latest_matrix)
        capability_selection = self._capability_selection_audit(agent_dir)
        runtime_os = self._runtime_os_summary(agent_dir, latest)
        evidence_health = self._evidence_health(route_guidance, matrix_route_guidance, runtime_os)
        next_actions = self._next_actions(
            latest,
            capability_summary,
            failure_types,
            blockers,
            model_profiles,
            route_guidance,
            matrix_route_guidance,
            runtime_os,
        )
        return CapabilityReportResult(
            root=self.root,
            acceptance_runs=len(acceptance_runs),
            latest_acceptance=self._latest_summary(latest),
            capability_summary=capability_summary,
            failure_types=failure_types,
            average_repair_rounds=repair_rounds,
            model_calls=model_calls,
            tool_calls=tool_calls,
            tool_budget_units=tool_budget_units,
            max_context_estimated_tokens=max_context_estimated_tokens,
            max_context_window_ratio=max_context_window_ratio,
            context_sections=context_sections,
            context_duplicate_content_hashes=context_duplicate_content_hashes,
            model_profiles=model_profiles,
            model_profile_path=model_profile_path,
            route_guidance=route_guidance,
            latest_real_provider_matrix=latest_matrix,
            matrix_route_guidance=matrix_route_guidance,
            capability_selection=capability_selection,
            runtime_os=runtime_os,
            evidence_health=evidence_health,
            common_blockers=blockers,
            next_actions=next_actions,
        )

    def _acceptance_history(self, agent_dir: Path) -> list[dict[str, Any]]:
        path = agent_dir / "acceptance" / "history.jsonl"
        if not path.exists():
            return []
        return [enrich_acceptance_report(item) for item in self.jsonl.read_all(path, None)]

    def _latest_acceptance(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "acceptance" / "acceptance_report.json"
        if not path.exists():
            return {}
        return enrich_acceptance_report(self.store.read(path, "acceptance_report"))

    def _capability_summary(
        self,
        history: list[dict[str, Any]],
        latest: dict[str, Any],
    ) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        sources = history or ([latest] if latest else [])
        for report in sources:
            metadata = acceptance_metadata_index(report)
            closed_failures = self._closed_failures(report)
            for scenario in report.get("scenarios", []):
                if not isinstance(scenario, dict):
                    continue
                scenario = enrich_acceptance_scenario(scenario, metadata)
                capability = str(scenario.get("capability") or "unknown")
                item = summary.setdefault(capability, {"total": 0, "passed": 0, "failed": 0})
                item["total"] += 1
                scenario_name = str(scenario.get("scenario") or "")
                if scenario.get("ok") or scenario_name in closed_failures:
                    item["passed"] += 1
                else:
                    item["failed"] += 1
        return summary

    def _execution_evidence_summary(
        self,
        agent_dir: Path,
    ) -> tuple[dict[str, int], list[str], float]:
        failure_types: dict[str, int] = {}
        blocker_counts: dict[str, int] = {}
        repair_counts: list[int] = []
        self._acceptance_failure_summary(agent_dir, failure_types, blocker_counts)
        for run_dir in self._run_dirs(agent_dir):
            evidence_path = run_dir / "task_execution_evidence.jsonl"
            evidence_items = (
                self.jsonl.read_all(evidence_path, "task_execution_evidence")
                if evidence_path.exists()
                else []
            )
            repair_counts.append(
                len(
                    [
                        item
                        for item in evidence_items
                        if item.get("failure_type")
                        in {"repair_contract_violation", "repair_exception"}
                    ]
                )
            )
            for item in evidence_items:
                if item.get("status") not in {"blocked", "failed"}:
                    continue
                failure_type = str(item.get("failure_type") or "unknown")
                failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
                summary = str(item.get("summary") or failure_type)
                blocker_counts[summary] = blocker_counts.get(summary, 0) + 1
        blockers = [
            item
            for item, _count in sorted(blocker_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        average = sum(repair_counts) / len(repair_counts) if repair_counts else 0.0
        return failure_types, blockers, average

    def _acceptance_failure_summary(
        self,
        agent_dir: Path,
        failure_types: dict[str, int],
        blocker_counts: dict[str, int],
    ) -> None:
        for report in self._acceptance_history(agent_dir) or [self._latest_acceptance(agent_dir)]:
            if not report:
                continue
            closed_failures = self._closed_failures(report)
            for scenario in report.get("scenarios", []):
                scenario_name = str(scenario.get("scenario") or "")
                if (
                    not isinstance(scenario, dict)
                    or scenario.get("ok")
                    or scenario_name in closed_failures
                ):
                    continue
                attribution = scenario.get("failure_attribution")
                attribution = attribution if isinstance(attribution, dict) else {}
                if not attribution or not attribution.get("category"):
                    attribution = classify_failure_attribution(scenario)
                failure_type = str(attribution.get("category") or "acceptance_scenario_failure")
                failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
                summary = str(
                    scenario.get("failure_summary")
                    or scenario.get("stderr_tail")
                    or scenario.get("scenario")
                    or failure_type
                )
                blocker_counts[summary] = blocker_counts.get(summary, 0) + 1

    def _cost_signals(self, agent_dir: Path) -> tuple[
        int,
        int,
        int,
        int,
        float,
        dict[str, int],
        list[str],
    ]:
        model_calls = 0
        tool_calls = 0
        tool_budget_units = 0
        max_context_estimated_tokens = 0
        max_context_window_ratio = 0.0
        context_sections: dict[str, int] = {}
        duplicate_hashes: list[str] = []
        for run_dir in self._run_dirs(agent_dir):
            cost_path = run_dir / "cost_report.json"
            if cost_path.exists():
                cost = self.store.read(cost_path, "cost_report")
                model_calls += int(cost.get("model_calls") or 0)
                tool_calls += int(cost.get("tool_calls") or 0)
                tool_budget_units += int(cost.get("tool_budget_units", cost.get("tool_calls") or 0))
                max_context_estimated_tokens = max(
                    max_context_estimated_tokens,
                    int(cost.get("max_context_estimated_tokens") or 0),
                )
                max_context_window_ratio = max(
                    max_context_window_ratio,
                    float(cost.get("context_window_ratio") or 0.0),
                )
                raw_sections = cost.get("max_context_sections") or cost.get(
                    "latest_context_sections"
                )
                if isinstance(raw_sections, dict):
                    for key, value in raw_sections.items():
                        context_sections[str(key)] = max(
                            context_sections.get(str(key), 0),
                            int(value or 0),
                        )
                raw_hashes = cost.get("context_duplicate_content_hashes")
                if isinstance(raw_hashes, list):
                    duplicate_hashes.extend(str(item) for item in raw_hashes)
        return (
            model_calls,
            tool_calls,
            tool_budget_units,
            max_context_estimated_tokens,
            max_context_window_ratio,
            dict(sorted(context_sections.items())),
            list(dict.fromkeys(duplicate_hashes))[:20],
        )

    def _model_profiles(self, agent_dir: Path) -> list[dict[str, Any]]:
        profiles: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for run_dir in self._run_dirs(agent_dir):
            path = run_dir / "model_calls.jsonl"
            calls = self.jsonl.read_all(path, "model_call") if path.exists() else []
            for call in calls:
                key = (
                    str(call.get("model_provider") or "unknown"),
                    str(call.get("model_name") or "unknown"),
                    str(call.get("purpose") or "unknown"),
                    str(call.get("model_tier") or "unknown"),
                )
                profile = self._ensure_model_profile(profiles, key)
                profile["total_calls"] += 1
                if call.get("status") == "success":
                    profile["success_calls"] += 1
                else:
                    profile["failure_calls"] += 1
                    failure_type = self._classify_model_failure(call)
                    profile["failure_types"][failure_type] = (
                        profile["failure_types"].get(failure_type, 0) + 1
                    )
                    if len(profile["recent_failures"]) < 5:
                        profile["recent_failures"].append(str(call.get("summary") or failure_type))
                profile["input_tokens"] += int(call.get("input_tokens") or 0)
                profile["output_tokens"] += int(call.get("output_tokens") or 0)
            self._merge_worker_profile_signals(run_dir, profiles)
            self._merge_observation_route_signals(run_dir, profiles)
        self._merge_real_provider_matrix_signals(agent_dir, profiles)

        normalized = []
        for profile in profiles.values():
            total = int(profile["total_calls"])
            profile["success_rate"] = (
                round(int(profile["success_calls"]) / total, 4) if total else 0.0
            )
            profile["average_input_tokens"] = (
                round(int(profile["input_tokens"]) / total, 2) if total else 0.0
            )
            profile["average_output_tokens"] = (
                round(int(profile["output_tokens"]) / total, 2) if total else 0.0
            )
            total_workers = int(profile.get("total_workers") or 0)
            profile["worker_success_rate"] = (
                round(int(profile["successful_workers"]) / total_workers, 4)
                if total_workers
                else 0.0
            )
            validation_total = int(profile.get("validation_total") or 0)
            profile["validation_pass_rate"] = (
                round(int(profile["validation_passed"]) / validation_total, 4)
                if validation_total
                else 0.0
            )
            runtime_request_total = int(profile.get("runtime_request_total") or 0)
            profile["runtime_request_rate"] = round(
                runtime_request_total / max(1, total_workers),
                4,
            )
            route_signal_total = int(profile.get("route_signal_total") or 0)
            profile["route_signal_success_rate"] = (
                round(int(profile["route_signal_success"]) / route_signal_total, 4)
                if route_signal_total
                else 0.0
            )
            matrix_signal_total = int(profile.get("matrix_signal_total") or 0)
            profile["matrix_signal_success_rate"] = (
                round(int(profile["matrix_signal_success"]) / matrix_signal_total, 4)
                if matrix_signal_total
                else 0.0
            )
            profile["recommended_action"] = self._model_route_action(profile)
            normalized.append(profile)
        return sorted(
            normalized,
            key=lambda item: (
                str(item["provider"]),
                str(item["model"]),
                str(item["purpose"]),
                str(item["model_tier"]),
            ),
        )

    def _runtime_os_summary(
        self,
        agent_dir: Path,
        latest: dict[str, Any],
    ) -> dict[str, Any]:
        scenarios = [item for item in latest.get("scenarios", []) if isinstance(item, dict)]
        required = str(latest.get("suite") or "") in {"core", "nightly"}
        evidence = runtime_os_release_evidence(self._run_dirs(agent_dir), self._read_jsonl)
        evidence.update(runtime_os_acceptance_evidence(scenarios))
        summary = runtime_os_full_summary(latest, scenarios, evidence, required=required)
        raw_gate = summary.get("gate")
        gate: dict[str, Any] = raw_gate if isinstance(raw_gate, dict) else {}
        if (
            latest.get("ok")
            and summary.get("status") == "fail"
            and gate.get("missing_capabilities")
            and int(evidence.get("acceptance_runtime_os_scenarios") or 0) >= 1
        ):
            summary["evidence_class"] = "historical_evidence_noise"
            summary["staleness"] = "superseded_by_current_regression_gates"
        summary["catalog"] = runtime_os_catalog_report()
        return summary

    def _ensure_model_profile(
        self,
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
        key: tuple[str, str, str, str],
    ) -> dict[str, Any]:
        return profiles.setdefault(
            key,
            {
                "provider": key[0],
                "model": key[1],
                "purpose": key[2],
                "model_tier": key[3],
                "total_calls": 0,
                "success_calls": 0,
                "failure_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_workers": 0,
                "successful_workers": 0,
                "failed_workers": 0,
                "validation_total": 0,
                "validation_passed": 0,
                "runtime_request_total": 0,
                "runtime_request_types": {},
                "route_signal_total": 0,
                "route_signal_success": 0,
                "route_signal_failure": 0,
                "route_signal_success_rate": 0.0,
                "route_task_kinds": {},
                "route_decisions": {},
                "recent_route_signals": [],
                "matrix_signal_total": 0,
                "matrix_signal_success": 0,
                "matrix_signal_failure": 0,
                "matrix_signal_success_rate": 0.0,
                "matrix_task_kinds": {},
                "matrix_routes": {},
                "recent_matrix_signals": [],
                "merge_gate_blocks": 0,
                "failure_types": {},
                "recent_failures": [],
            },
        )

    def _merge_real_provider_matrix_signals(
        self,
        agent_dir: Path,
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> None:
        matrix_root = agent_dir / "verification" / "real_provider_matrix"
        if not matrix_root.exists():
            return
        for summary_path in sorted(matrix_root.glob("*/matrix_summary.json")):
            try:
                summary = self.store.read(summary_path, "real_provider_matrix_summary")
            except (OSError, ValueError):
                continue
            created_at = str(summary.get("created_at") or "")
            cases = [item for item in summary.get("cases", []) if isinstance(item, dict)]
            for case in cases:
                profile = self._profile_from_matrix_case(case, profiles)
                ok = case.get("ok") is True
                task_kind = str(case.get("task_kind") or "unknown")
                route = str(case.get("route") or "unknown")
                profile["matrix_signal_total"] += 1
                if ok:
                    profile["matrix_signal_success"] += 1
                else:
                    profile["matrix_signal_failure"] += 1
                    failure_type = str(case.get("failure_type") or "matrix_case_failed")
                    profile["failure_types"][failure_type] = (
                        profile["failure_types"].get(failure_type, 0) + 1
                    )
                    if len(profile["recent_failures"]) < 5:
                        profile["recent_failures"].append(
                            str(case.get("failure_summary") or failure_type)
                        )
                profile["matrix_task_kinds"][task_kind] = (
                    profile["matrix_task_kinds"].get(task_kind, 0) + 1
                )
                profile["matrix_routes"][route] = profile["matrix_routes"].get(route, 0) + 1
                if len(profile["recent_matrix_signals"]) < 5:
                    status = "success" if ok else "failure"
                    profile["recent_matrix_signals"].append(
                        f"{created_at}:{task_kind}:{route}:{status}"
                    )

    def _profile_from_matrix_case(
        self,
        case: dict[str, Any],
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        workspace = Path(str(case.get("workspace") or ""))
        calls: list[dict[str, Any]] = []
        runs_dir = workspace / ".asteria" / "runs"
        if runs_dir.exists():
            for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
                calls.extend(self._read_jsonl(run_dir / "model_calls.jsonl", "model_call"))
        if calls:
            return self._profile_from_latest_call(calls, profiles)
        key = (
            str(case.get("provider") or "unknown"),
            str(case.get("model") or "unknown"),
            str(case.get("purpose") or "real_provider_matrix"),
            str(case.get("model_tier") or "unknown"),
        )
        return self._ensure_model_profile(profiles, key)

    def _merge_observation_route_signals(
        self,
        run_dir: Path,
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> None:
        plans_path = run_dir / "observation_plans.jsonl"
        if not plans_path.exists():
            return
        calls = self._read_jsonl(run_dir / "model_calls.jsonl", "model_call")
        if not calls:
            return
        profile_by_task = self._profile_by_task_from_runtime(run_dir, profiles)
        task_kind_by_id = self._task_kind_by_id(run_dir)
        done_tasks = self._done_task_ids(run_dir)
        plans = self._read_jsonl(plans_path, "observation_plan")
        for plan in plans:
            task_id = str(plan.get("task_id") or "")
            profile = profile_by_task.get(task_id) or self._profile_from_latest_call(calls, profiles)
            route = str(plan.get("recommended_route") or "unknown")
            task_kind = task_kind_by_id.get(task_id, "unknown")
            success = task_id in done_tasks if task_id else False
            profile["route_signal_total"] += 1
            if success:
                profile["route_signal_success"] += 1
            else:
                profile["route_signal_failure"] += 1
            profile["route_task_kinds"][task_kind] = profile["route_task_kinds"].get(task_kind, 0) + 1
            profile["route_decisions"][route] = profile["route_decisions"].get(route, 0) + 1
            if len(profile["recent_route_signals"]) < 5:
                profile["recent_route_signals"].append(
                    f"{task_kind}:{route}:{'success' if success else 'failure'}"
                )

    def _profile_from_latest_call(
        self,
        calls: list[dict[str, Any]],
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        latest_call = calls[-1]
        key = (
            str(latest_call.get("model_provider") or "unknown"),
            str(latest_call.get("model_name") or "unknown"),
            str(latest_call.get("purpose") or "unknown"),
            str(latest_call.get("model_tier") or "unknown"),
        )
        return self._ensure_model_profile(profiles, key)

    def _profile_by_task_from_runtime(
        self,
        run_dir: Path,
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        workers_path = run_dir / "workers.jsonl"
        runtime_profiles_path = run_dir / "runtime_profiles.jsonl"
        model_profiles_path = run_dir / "model_profiles.jsonl"
        if not (
            workers_path.exists()
            and runtime_profiles_path.exists()
            and model_profiles_path.exists()
        ):
            return {}
        model_profiles = {
            item["model_profile_id"]: item
            for item in self.jsonl.read_all(model_profiles_path, "model_profile")
            if item.get("model_profile_id")
        }
        runtime_profiles = {
            item["runtime_profile_id"]: item
            for item in self.jsonl.read_all(runtime_profiles_path, "runtime_profile")
            if item.get("runtime_profile_id")
        }
        profile_by_task: dict[str, dict[str, Any]] = {}
        for worker in self.jsonl.read_all(workers_path, "worker_invocation"):
            runtime_profile = runtime_profiles.get(str(worker.get("runtime_profile_id") or ""))
            if not runtime_profile:
                continue
            model_profile = model_profiles.get(str(runtime_profile.get("model_profile_id") or ""))
            if not model_profile:
                continue
            key = (
                str(model_profile.get("provider") or "unknown"),
                str(model_profile.get("model_name") or "unknown"),
                str(model_profile.get("purpose") or "unknown"),
                str(model_profile.get("model_tier") or "unknown"),
            )
            profile_by_task[str(worker.get("task_id") or "")] = self._ensure_model_profile(
                profiles,
                key,
            )
        return profile_by_task

    def _task_kind_by_id(self, run_dir: Path) -> dict[str, str]:
        path = run_dir / "task_plan.json"
        if not path.exists():
            return {}
        board = self.store.read(path, "task_board")
        return {
            str(task.get("task_id")): str(task.get("task_kind") or "unknown")
            for task in board.get("tasks", [])
            if task.get("task_id")
        }

    def _done_task_ids(self, run_dir: Path) -> set[str]:
        path = run_dir / "task_plan.json"
        if not path.exists():
            return set()
        board = self.store.read(path, "task_board")
        return {
            str(task.get("task_id"))
            for task in board.get("tasks", [])
            if task.get("task_id") and task.get("status") == "done"
        }

    def _merge_worker_profile_signals(
        self,
        run_dir: Path,
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> None:
        workers_path = run_dir / "workers.jsonl"
        worker_results_path = run_dir / "worker_results.jsonl"
        runtime_profiles_path = run_dir / "runtime_profiles.jsonl"
        model_profiles_path = run_dir / "model_profiles.jsonl"
        if not (
            workers_path.exists()
            and worker_results_path.exists()
            and runtime_profiles_path.exists()
            and model_profiles_path.exists()
        ):
            return
        model_profiles = {
            item["model_profile_id"]: item
            for item in self.jsonl.read_all(model_profiles_path, "model_profile")
            if item.get("model_profile_id")
        }
        runtime_profiles = {
            item["runtime_profile_id"]: item
            for item in self.jsonl.read_all(runtime_profiles_path, "runtime_profile")
            if item.get("runtime_profile_id")
        }
        workers = {
            item["worker_invocation_id"]: item
            for item in self.jsonl.read_all(workers_path, "worker_invocation")
            if item.get("worker_invocation_id")
        }
        validations = (
            {
                item["validation_result_id"]: item
                for item in self.jsonl.read_all(
                    run_dir / "validation_results.jsonl", "validation_result"
                )
                if item.get("validation_result_id")
            }
            if (run_dir / "validation_results.jsonl").exists()
            else {}
        )
        for result in self.jsonl.read_all(worker_results_path, "worker_result"):
            worker = workers.get(result.get("worker_invocation_id"))
            if not worker:
                continue
            runtime_profile = runtime_profiles.get(worker.get("runtime_profile_id"))
            if not runtime_profile:
                continue
            model_profile = model_profiles.get(runtime_profile.get("model_profile_id"))
            if not model_profile:
                continue
            key = (
                str(model_profile.get("provider") or "unknown"),
                str(model_profile.get("model_name") or "unknown"),
                str(model_profile.get("purpose") or "unknown"),
                str(model_profile.get("model_tier") or "unknown"),
            )
            profile = self._ensure_model_profile(profiles, key)
            profile["total_workers"] += 1
            if result.get("status") == "succeeded":
                profile["successful_workers"] += 1
            else:
                profile["failed_workers"] += 1
                failure_type = str(result.get("status") or "worker_failed")
                profile["failure_types"][failure_type] = (
                    profile["failure_types"].get(failure_type, 0) + 1
                )
                if len(profile["recent_failures"]) < 5:
                    profile["recent_failures"].append(str(result.get("summary") or failure_type))
            raw_validation_refs = result.get("validation_refs")
            validation_refs = raw_validation_refs if isinstance(raw_validation_refs, list) else []
            for ref in validation_refs:
                validation = validations.get(ref)
                if not validation:
                    continue
                profile["validation_total"] += 1
                if validation.get("status") == "passed":
                    profile["validation_passed"] += 1
        profile_by_task = self._latest_profile_by_task(
            workers,
            runtime_profiles,
            model_profiles,
            profiles,
        )
        runtime_requests_path = run_dir / "runtime_requests.jsonl"
        if runtime_requests_path.exists():
            for request in self.jsonl.read_all(runtime_requests_path, "runtime_request"):
                request_profile = profile_by_task.get(str(request.get("task_id") or ""))
                if not request_profile:
                    continue
                request_profile["runtime_request_total"] += 1
                request_type = str(request.get("request_type") or "unknown")
                request_profile["runtime_request_types"][request_type] = (
                    request_profile["runtime_request_types"].get(request_type, 0) + 1
                )
        evidence_path = run_dir / "task_execution_evidence.jsonl"
        if evidence_path.exists():
            for evidence in self.jsonl.read_all(evidence_path, "task_execution_evidence"):
                evidence_profile = profile_by_task.get(str(evidence.get("task_id") or ""))
                if not evidence_profile:
                    continue
                contract = evidence.get("contract_check")
                contract = contract if isinstance(contract, dict) else {}
                merge_gate = contract.get("merge_gate")
                if isinstance(merge_gate, dict) and merge_gate.get("ok") is False:
                    evidence_profile["merge_gate_blocks"] += 1
                    evidence_profile["failure_types"]["merge_gate"] = (
                        evidence_profile["failure_types"].get("merge_gate", 0) + 1
                    )

    def _latest_profile_by_task(
        self,
        workers: dict[str, dict[str, Any]],
        runtime_profiles: dict[str, dict[str, Any]],
        model_profiles: dict[str, dict[str, Any]],
        profiles: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        by_task: dict[str, dict[str, Any]] = {}
        for worker in workers.values():
            runtime_profile = runtime_profiles.get(str(worker.get("runtime_profile_id") or ""))
            if not runtime_profile:
                continue
            model_profile = model_profiles.get(str(runtime_profile.get("model_profile_id") or ""))
            if not model_profile:
                continue
            key = (
                str(model_profile.get("provider") or "unknown"),
                str(model_profile.get("model_name") or "unknown"),
                str(model_profile.get("purpose") or "unknown"),
                str(model_profile.get("model_tier") or "unknown"),
            )
            by_task[str(worker.get("task_id") or "")] = self._ensure_model_profile(profiles, key)
        return by_task

    def _write_model_profile(
        self,
        agent_dir: Path,
        profiles: list[dict[str, Any]],
    ) -> Path | None:
        if not profiles:
            return None
        path = agent_dir / "model" / "capability_profile.json"
        profile = {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "profile_count": len(profiles),
            "profiles": profiles,
        }
        self.store.write(path, profile, "model_capability_profile")
        return path

    def _classify_model_failure(self, call: dict[str, Any]) -> str:
        summary = str(call.get("summary") or "").lower()
        if "json" in summary or "schema" in summary:
            return "provider_response"
        if "rate" in summary or "429" in summary:
            return "rate_limited"
        if "timeout" in summary or "timed out" in summary:
            return "timeout"
        if "auth" in summary or "api key" in summary or "401" in summary or "403" in summary:
            return "authentication"
        if "budget" in summary:
            return "budget"
        if "network" in summary or "tls" in summary or "connection" in summary:
            return "network"
        return "model_call_failed"

    def _model_route_action(self, profile: dict[str, Any]) -> str:
        total = int(profile.get("total_calls") or 0)
        success_rate = float(profile.get("success_rate") or 0.0)
        total_workers = int(profile.get("total_workers") or 0)
        worker_success_rate = float(profile.get("worker_success_rate") or 0.0)
        validation_total = int(profile.get("validation_total") or 0)
        validation_pass_rate = float(profile.get("validation_pass_rate") or 0.0)
        failure_types = profile.get("failure_types") or {}
        matrix_signal_total = int(profile.get("matrix_signal_total") or 0)
        matrix_signal_success_rate = float(profile.get("matrix_signal_success_rate") or 0.0)
        if matrix_signal_total >= 1 and matrix_signal_success_rate < 1.0:
            return "review_real_provider_matrix_before_scaling"
        if validation_total >= 2 and validation_pass_rate < 0.8:
            return "review_validation_or_route_before_scaling"
        if int(profile.get("merge_gate_blocks") or 0) >= 2:
            return "review_merge_quality_before_scaling"
        if float(profile.get("runtime_request_rate") or 0.0) >= 1.0 and total_workers >= 2:
            return "improve_planner_scope_before_scaling"
        if total_workers >= 2 and worker_success_rate < 0.8:
            return "review_worker_route_before_scaling"
        if total < 2 and total_workers < 2:
            return "collect_more_data"
        if success_rate >= 0.8:
            return "keep_route"
        if total == 0 and total_workers >= 2 and worker_success_rate >= 0.8:
            return "keep_route"
        if failure_types.get("authentication") or failure_types.get("budget"):
            return "pause_route_until_config_fixed"
        if (
            failure_types.get("rate_limited")
            or failure_types.get("timeout")
            or failure_types.get("network")
        ):
            return "fallback_or_retry_later"
        if failure_types.get("provider_response"):
            return "use_json_stricter_or_switch_model"
        return "review_route_before_scaling"

    def _run_dirs(self, agent_dir: Path) -> list[Path]:
        if not agent_dir.exists():
            return []
        runs_dir = agent_dir / "runs"
        try:
            run_store = RunStore(agent_dir, self.validator)
            listed = [run_store.run_dir(str(run["run_id"])) for run in run_store.list_sessions()]
            if runs_dir.exists():
                known = {path.name for path in listed}
                listed.extend(
                    path for path in runs_dir.iterdir() if path.is_dir() and path.name not in known
                )
            return listed
        except (FileNotFoundError, RuntimeError, KeyError):
            return (
                [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []
            )

    def _read_jsonl(self, path: Path, schema_name: str | None = None) -> list[dict[str, Any]]:
        return self.jsonl.read_all(path, schema_name) if path.exists() else []

    def _latest_summary(self, latest: dict[str, Any]) -> dict[str, Any]:
        if not latest:
            return {}
        raw_aggregate = latest.get("aggregate")
        aggregate: dict[str, Any] = raw_aggregate if isinstance(raw_aggregate, dict) else {}
        failed = int(aggregate.get("failed") or 0)
        trend = latest.get("trend_warnings") or []
        raw_closure = latest.get("repair_closure")
        closure: dict[str, Any] = raw_closure if isinstance(raw_closure, dict) else {}
        closure_ok = closure.get("rerun_ok") is True and not closure.get("remaining_failures", [])
        closed_failures = set(closure.get("closed_failures", [])) if closure_ok else set()
        effective_passed = int(aggregate.get("passed") or 0) + len(closed_failures)
        effective_failed = max(0, failed - len(closed_failures))
        release_validation = "acceptance_passed"
        if effective_failed and not closure_ok:
            release_validation = "blocked"
        elif trend or latest.get("repair_closure"):
            release_validation = "conditional"
        return {
            "ok": bool(latest.get("ok")) or (closure_ok and effective_failed == 0),
            "base_ok": bool(latest.get("ok")),
            "suite": latest.get("suite"),
            "total": int(aggregate.get("total") or len(latest.get("scenarios", []))),
            "passed": effective_passed,
            "failed": effective_failed,
            "release_validation": release_validation,
        }

    def _next_actions(
        self,
        latest: dict[str, Any],
        capability_summary: dict[str, dict[str, int]],
        failure_types: dict[str, int],
        blockers: list[str],
        model_profiles: list[dict[str, Any]],
        route_guidance: dict[str, Any],
        matrix_route_guidance: dict[str, Any],
        runtime_os: dict[str, Any],
    ) -> list[str]:
        actions = []
        if not latest:
            actions.append("Run `asteria /acceptance --suite core` to establish a baseline.")
        elif not latest.get("ok") and not self._closed_failures(latest):
            actions.append(
                "Run `asteria /acceptance --promote-failures --run-promoted --rerun-promoted`."
            )
        weak = [
            name
            for name, summary in capability_summary.items()
            if summary.get("failed", 0) or summary.get("total", 0) == 0
        ]
        if weak:
            actions.append("Prioritize weak capabilities: " + ", ".join(sorted(weak)[:5]))
        if failure_types:
            actions.append("Use `/replan` and `/debug` on the latest execution evidence failures.")
        if blockers:
            actions.append("Inspect the most common blocker evidence before widening scope.")
        weak_models = [
            profile
            for profile in model_profiles
            if int(profile.get("total_calls") or 0) >= 2
            and float(profile.get("success_rate") or 0.0) < 0.8
            and not self._profile_superseded_by_route_guidance(profile, route_guidance)
        ]
        if weak_models:
            labels = [
                f"{item['provider']}/{item['model']}:{item['purpose']}" for item in weak_models[:3]
            ]
            actions.append(
                "Review weak model routes before scaling long-run work: " + ", ".join(labels)
            )
        if route_guidance.get("status") in {"blocked", "review"}:
            actions.extend(str(item) for item in route_guidance.get("recommended_actions", []))
        if matrix_route_guidance.get("status") in {"blocked", "review"}:
            actions.extend(
                str(item) for item in matrix_route_guidance.get("recommended_actions", [])
            )
        if (
            runtime_os.get("status") in {"fail", "partial", "missing_acceptance"}
            and runtime_os.get("evidence_class") != "historical_evidence_noise"
        ):
            actions.append(
                "Run Runtime OS core acceptance and gate before release: "
                "`asteria /acceptance --suite core` then `asteria /acceptance-gate --suite core`."
            )
        if not model_profiles:
            actions.append("Run a long-run or acceptance cycle to collect model capability data.")
        return list(dict.fromkeys(actions))

    def _evidence_health(
        self,
        route_guidance: dict[str, Any],
        matrix_route_guidance: dict[str, Any],
        runtime_os: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_status = str(runtime_os.get("status") or "unknown")
        raw_gate = runtime_os.get("gate")
        gate: dict[str, Any] = raw_gate if isinstance(raw_gate, dict) else {}
        missing_capabilities = list(gate.get("missing_capabilities") or [])
        missing_evidence = list(gate.get("missing_evidence") or [])
        if (
            missing_capabilities
            and runtime_os.get("evidence_class") == "historical_evidence_noise"
        ):
            return {
                "status": "historical_evidence_noise",
                "summary": (
                    "Historical Runtime OS catalog evidence is stale; current regression gates "
                    "are healthy, so treat these as cleanup targets instead of release blockers."
                ),
                "missing_capabilities": missing_capabilities[:10],
                "missing_evidence": missing_evidence[:10],
            }
        if missing_capabilities:
            return {
                "status": "implementation_gap",
                "summary": "Runtime OS catalog still has missing capability implementation.",
                "missing_capabilities": missing_capabilities[:10],
                "missing_evidence": missing_evidence[:10],
            }
        if missing_evidence:
            return {
                "status": "evidence_gap",
                "summary": "Runtime OS capability exists, but release evidence is incomplete.",
                "missing_capabilities": [],
                "missing_evidence": missing_evidence[:10],
            }
        if route_guidance.get("status") == "blocked":
            return {
                "status": "route_health_blocked",
                "summary": "Provider route health blocks widening validation.",
                "recommended_actions": list(route_guidance.get("recommended_actions") or [])[:5],
            }
        if matrix_route_guidance.get("status") == "blocked":
            return {
                "status": "real_provider_matrix_blocked",
                "summary": "Latest real-provider matrix needs repair before widening validation.",
                "recommended_actions": list(matrix_route_guidance.get("recommended_actions") or [])[:5],
            }
        if runtime_status in {"pass", "ready"}:
            return {
                "status": "ready",
                "summary": "Implementation and evidence are aligned for the current release scope.",
            }
        return {
            "status": runtime_status,
            "summary": "Capability evidence is not yet sufficient for release readiness.",
        }

    def _matrix_route_guidance(self, matrix: dict[str, Any]) -> dict[str, Any]:
        if not matrix:
            return {}
        route = str(matrix.get("latest_route") or "unknown")
        task_kind = str(matrix.get("latest_task_kind") or "unknown")
        case = str(matrix.get("latest_case") or "unknown")
        reason = str(matrix.get("latest_reason") or "No reason recorded.")
        summary_path = str(matrix.get("summary_path") or "")
        evidence_refs = [str(ref) for ref in matrix.get("latest_evidence_refs") or []][:5]
        if matrix.get("ok") is True:
            return {
                "status": "healthy",
                "latest_route": route,
                "latest_task_kind": task_kind,
                "latest_case": case,
                "reason": reason,
                "evidence_refs": evidence_refs,
                "summary_path": summary_path,
                "recommended_actions": [],
            }
        actions = [
            (
                "Repair latest real-provider P0 matrix failure before widening validation: "
                f"{case} requires {route} for task_kind={task_kind}."
            )
        ]
        actions.append(self._matrix_route_action(route, case))
        evidence = ", ".join(evidence_refs[:3]) if evidence_refs else "no evidence refs recorded"
        if summary_path:
            actions.append(f"Inspect {summary_path} and evidence refs: {evidence}.")
        return {
            "status": "blocked",
            "latest_route": route,
            "latest_task_kind": task_kind,
            "latest_case": case,
            "reason": reason,
            "evidence_refs": evidence_refs,
            "summary_path": summary_path,
            "recommended_actions": actions,
        }

    def _matrix_route_action(self, route: str, case: str) -> str:
        if route == "repair":
            return (
                "Run targeted repair/debug, then rerun "
                f"`asteria real-model-smoke --matrix p0 --matrix-case {case}`."
            )
        if route == "replan":
            return (
                "Replan the contract mismatch, then rerun "
                f"`asteria real-model-smoke --matrix p0 --matrix-case {case}`."
            )
        if route == "ask":
            return "Resolve the permission or scope DecisionPoint before retrying the matrix case."
        if route == "stop":
            return "Stop widening real-provider validation work until repeated no-new-evidence is diagnosed."
        return (
            "Review the latest real-provider matrix route decision, then rerun "
            f"`asteria real-model-smoke --matrix p0 --matrix-case {case}`."
        )

    def _normalized_route_guidance(
        self,
        latest: dict[str, Any],
        route_guidance: dict[str, Any],
    ) -> dict[str, Any]:
        if route_guidance.get("status") not in {"blocked", "review"} or not latest.get("ok"):
            return route_guidance
        strategy = route_guidance.get("provider_route_strategy")
        strategy = strategy if isinstance(strategy, dict) else {}
        if strategy.get("decision") == "continue_primary":
            review = [
                item
                for item in route_guidance.get("review") or []
                if isinstance(item, dict)
            ]
            active_review = [
                item for item in review if not _route_hint_matches_strategy(item, strategy)
            ]
            superseded_review = [
                {**item, "release_evidence_status": "superseded", "severity": 1}
                for item in review
                if _route_hint_matches_strategy(item, strategy)
            ]
            if active_review != review:
                status = "review" if active_review else "healthy"
                return {
                    **route_guidance,
                    "status": status,
                    "review": active_review,
                    "superseded_review": superseded_review,
                    "staleness": "superseded_by_latest_acceptance_and_route_evidence",
                    "recommended_actions": []
                    if status == "healthy"
                    else list(route_guidance.get("recommended_actions") or []),
                }
        if route_guidance.get("status") != "blocked":
            return route_guidance
        normalized = dict(route_guidance)
        normalized["status"] = "review"
        normalized["staleness"] = "superseded_by_latest_acceptance"
        normalized["recommended_actions"] = [
            "Latest acceptance is healthy; collect fresh route evidence before widening long-run validation."
        ]
        return normalized

    def _profile_superseded_by_route_guidance(
        self,
        profile: dict[str, Any],
        route_guidance: dict[str, Any],
    ) -> bool:
        for item in route_guidance.get("superseded_review") or []:
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("provider") or "") == str(profile.get("provider") or "")
                and str(item.get("purpose") or "") == str(profile.get("purpose") or "")
                and _route_model_names_match(
                    str(item.get("model") or ""),
                    str(profile.get("model") or ""),
                )
            ):
                return True
        return False

    def _capability_selection_audit(self, agent_dir: Path) -> dict[str, Any]:
        summary = {"tasks": 0, "visible": 0, "selected": 0, "skipped": 0, "blocked": 0}
        reason_counts: dict[str, int] = {}
        examples: dict[str, list[str]] = {"selected": [], "skipped": [], "blocked": []}
        selected_capabilities: set[str] = set()
        visible_capabilities: set[str] = set()
        blocked_capabilities: set[str] = set()
        actual_capabilities: set[str] = set()
        for run_dir in self._run_dirs(agent_dir):
            dispatch = self._read_json(run_dir / "agent_loop_dispatch.json")
            task_dispatch = dispatch.get("task_dispatch")
            if not isinstance(task_dispatch, list):
                task_dispatch = []
            for item in task_dispatch:
                if isinstance(item, dict):
                    self._add_catalog_audit(
                        item,
                        summary,
                        reason_counts,
                        examples,
                        selected_capabilities,
                        visible_capabilities,
                        blocked_capabilities,
                    )
            actual_capabilities.update(self._actual_capabilities(run_dir))
        if summary["tasks"] == 0:
            return {}
        actual_not_selected = sorted(
            item for item in actual_capabilities if item not in selected_capabilities
        )
        actual_visible_not_selected = sorted(
            item for item in actual_not_selected if item in visible_capabilities
        )
        actual_catalog_blocked = sorted(
            item for item in actual_not_selected if item in blocked_capabilities
        )
        actual_missing_from_catalog = sorted(
            item for item in actual_not_selected if item not in visible_capabilities
        )
        return {
            "summary": summary,
            "reason_counts": reason_counts,
            "examples": examples,
            "actual_selection": {
                "actual_count": len(actual_capabilities),
                "actual_not_selected": actual_not_selected[:12],
                "actual_visible_not_selected": actual_visible_not_selected[:12],
                "actual_catalog_blocked": actual_catalog_blocked[:12],
                "actual_missing_from_catalog": actual_missing_from_catalog[:12],
            },
        }

    def _add_catalog_audit(
        self,
        task_dispatch: dict[str, Any],
        summary: dict[str, int],
        reason_counts: dict[str, int],
        examples: dict[str, list[str]],
        selected_capabilities: set[str],
        visible_capabilities: set[str],
        blocked_capabilities: set[str],
    ) -> None:
        catalog = task_dispatch.get("capability_catalog")
        if not isinstance(catalog, dict):
            return
        summary["tasks"] += 1
        catalog_summary = catalog.get("summary")
        if isinstance(catalog_summary, dict):
            for key in ("visible", "selected", "skipped", "blocked"):
                summary[key] += int(catalog_summary.get(key) or 0)
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            capability = f"{entry.get('capability_type')}:{entry.get('name')}"
            if entry.get("visible"):
                visible_capabilities.add(capability)
            state = str(entry.get("selection_state") or "unknown")
            if state == "selected":
                selected_capabilities.add(capability)
            elif state == "blocked":
                blocked_capabilities.add(capability)
            reason = str(entry.get("selection_reason") or state)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if state in examples and len(examples[state]) < 8:
                examples[state].append(f"{capability} - {reason}")

    def _actual_capabilities(self, run_dir: Path) -> set[str]:
        path = run_dir / "capability_decisions.jsonl"
        if not path.exists():
            return set()
        actual: set[str] = set()
        for item in self.jsonl.read_all(path, None):
            if not isinstance(item, dict):
                continue
            decision = item.get("decision")
            if isinstance(decision, dict) and decision.get("decision") == "deny":
                continue
            capability = str(item.get("capability") or item.get("name") or "")
            if capability:
                actual.add(f"{item.get('capability_type') or 'tool'}:{capability}")
        return actual

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = self.store.read(path, None)
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _closed_failures(self, report: dict[str, Any]) -> set[str]:
        closure = report.get("repair_closure")
        closure = closure if isinstance(closure, dict) else {}
        if closure.get("rerun_ok") is not True or closure.get("remaining_failures"):
            return set()
        return {str(item) for item in closure.get("closed_failures", [])}


def _route_hint_matches_strategy(item: dict[str, Any], strategy: dict[str, Any]) -> bool:
    if item.get("model_tier") != "strong":
        return False
    strategy_model = str(strategy.get("model") or "")
    current_model = str(strategy.get("current_model") or "")
    item_model = str(item.get("model") or "")
    return _route_model_names_match(item_model, strategy_model) or _route_model_names_match(
        item_model,
        current_model,
    )


def _route_model_names_match(left: str, right: str) -> bool:
    left = left.strip()
    right = right.strip()
    if left == right:
        return True
    glm5_aliases = {"glm-5", "glm-5.1"}
    return left in glm5_aliases and right in glm5_aliases
