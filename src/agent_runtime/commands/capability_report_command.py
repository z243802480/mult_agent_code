from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


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
    model_profiles: list[dict[str, Any]] = field(default_factory=list)
    model_profile_path: Path | None = None
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
                    f"Release readiness: {self.latest_acceptance.get('release_readiness')}",
                ]
            )
        if self.capability_summary:
            lines.append("Capabilities:")
            for capability, summary in sorted(self.capability_summary.items()):
                lines.append(
                    f"  - {capability}: {summary.get('passed', 0)}/"
                    f"{summary.get('total', 0)} passed"
                )
        if self.failure_types:
            lines.append("Failure types:")
            for failure_type, count in sorted(
                self.failure_types.items(), key=lambda item: (-item[1], item[0])
            )[:8]:
                lines.append(f"  - {failure_type}: {count}")
        lines.append(f"Average repair rounds: {self.average_repair_rounds:.2f}")
        lines.append(f"Cost signals: {self.model_calls} model calls, {self.tool_calls} tool calls")
        if self.model_profiles:
            lines.append("Model capability profiles:")
            for profile in self.model_profiles[:8]:
                lines.append(
                    "  - "
                    f"{profile['provider']}/{profile['model']} "
                    f"purpose={profile['purpose']} tier={profile['model_tier']}: "
                    f"{profile['success_rate']:.2f} success "
                    f"({profile['success_calls']}/{profile['total_calls']} calls, "
                    f"{profile['input_tokens']} in/{profile['output_tokens']} out tokens)"
                )
        if self.model_profile_path:
            lines.append(f"Model profile: {self.model_profile_path}")
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
        agent_dir = self.root / ".agent"
        acceptance_runs = self._acceptance_history(agent_dir)[-self.limit :]
        latest = acceptance_runs[-1] if acceptance_runs else self._latest_acceptance(agent_dir)
        capability_summary = self._capability_summary(acceptance_runs, latest)
        failure_types, blockers, repair_rounds = self._execution_evidence_summary(agent_dir)
        model_calls, tool_calls = self._cost_signals(agent_dir)
        model_profiles = self._model_profiles(agent_dir)
        model_profile_path = self._write_model_profile(agent_dir, model_profiles)
        next_actions = self._next_actions(
            latest,
            capability_summary,
            failure_types,
            blockers,
            model_profiles,
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
            model_profiles=model_profiles,
            model_profile_path=model_profile_path,
            common_blockers=blockers,
            next_actions=next_actions,
        )

    def _acceptance_history(self, agent_dir: Path) -> list[dict[str, Any]]:
        path = agent_dir / "acceptance" / "history.jsonl"
        if not path.exists():
            return []
        return self.jsonl.read_all(path, None)

    def _latest_acceptance(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "acceptance" / "acceptance_report.json"
        if not path.exists():
            return {}
        return self.store.read(path, "acceptance_report")

    def _capability_summary(
        self,
        history: list[dict[str, Any]],
        latest: dict[str, Any],
    ) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        sources = history or ([latest] if latest else [])
        for report in sources:
            metadata = {
                str(item.get("scenario")): item
                for item in report.get("scenario_metadata", [])
                if isinstance(item, dict)
            }
            for scenario in report.get("scenarios", []):
                if not isinstance(scenario, dict):
                    continue
                name = str(scenario.get("scenario") or "")
                capability = str(
                    scenario.get("capability")
                    or metadata.get(name, {}).get("capability")
                    or "unknown"
                )
                item = summary.setdefault(capability, {"total": 0, "passed": 0, "failed": 0})
                item["total"] += 1
                if scenario.get("ok"):
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
            for item, _count in sorted(
                blocker_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ]
        average = sum(repair_counts) / len(repair_counts) if repair_counts else 0.0
        return failure_types, blockers, average

    def _cost_signals(self, agent_dir: Path) -> tuple[int, int]:
        model_calls = 0
        tool_calls = 0
        for run_dir in self._run_dirs(agent_dir):
            cost_path = run_dir / "cost_report.json"
            if cost_path.exists():
                cost = self.store.read(cost_path, "cost_report")
                model_calls += int(cost.get("model_calls") or 0)
                tool_calls += int(cost.get("tool_calls") or 0)
        return model_calls, tool_calls

    def _model_profiles(self, agent_dir: Path) -> list[dict[str, Any]]:
        profiles: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for run_dir in self._run_dirs(agent_dir):
            path = run_dir / "model_calls.jsonl"
            if not path.exists():
                continue
            for call in self.jsonl.read_all(path, "model_call"):
                key = (
                    str(call.get("model_provider") or "unknown"),
                    str(call.get("model_name") or "unknown"),
                    str(call.get("purpose") or "unknown"),
                    str(call.get("model_tier") or "unknown"),
                )
                profile = profiles.setdefault(
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
                        "failure_types": {},
                        "recent_failures": [],
                    },
                )
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
        failure_types = profile.get("failure_types") or {}
        if total < 2:
            return "collect_more_data"
        if success_rate >= 0.8:
            return "keep_route"
        if failure_types.get("authentication") or failure_types.get("budget"):
            return "pause_route_until_config_fixed"
        if failure_types.get("rate_limited") or failure_types.get("timeout") or failure_types.get("network"):
            return "fallback_or_retry_later"
        if failure_types.get("provider_response"):
            return "use_json_stricter_or_switch_model"
        return "review_route_before_scaling"

    def _run_dirs(self, agent_dir: Path) -> list[Path]:
        if not agent_dir.exists():
            return []
        try:
            run_store = RunStore(agent_dir, self.validator)
            return [run_store.run_dir(str(run["run_id"])) for run in run_store.list_sessions()]
        except (FileNotFoundError, RuntimeError, KeyError):
            runs_dir = agent_dir / "runs"
            return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []

    def _latest_summary(self, latest: dict[str, Any]) -> dict[str, Any]:
        if not latest:
            return {}
        raw_aggregate = latest.get("aggregate")
        aggregate: dict[str, Any] = raw_aggregate if isinstance(raw_aggregate, dict) else {}
        failed = int(aggregate.get("failed") or 0)
        trend = latest.get("trend_warnings") or []
        release_readiness = "ready"
        if failed:
            release_readiness = "blocked"
        elif trend or latest.get("repair_closure"):
            release_readiness = "conditional"
        return {
            "ok": bool(latest.get("ok")),
            "suite": latest.get("suite"),
            "total": int(aggregate.get("total") or len(latest.get("scenarios", []))),
            "passed": int(aggregate.get("passed") or 0),
            "failed": failed,
            "release_readiness": release_readiness,
        }

    def _next_actions(
        self,
        latest: dict[str, Any],
        capability_summary: dict[str, dict[str, int]],
        failure_types: dict[str, int],
        blockers: list[str],
        model_profiles: list[dict[str, Any]],
    ) -> list[str]:
        actions = []
        if not latest:
            actions.append("Run `agent /acceptance --suite core` to establish a baseline.")
        elif not latest.get("ok"):
            actions.append(
                "Run `agent /acceptance --promote-failures --run-promoted --rerun-promoted`."
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
        ]
        if weak_models:
            labels = [
                f"{item['provider']}/{item['model']}:{item['purpose']}"
                for item in weak_models[:3]
            ]
            actions.append("Review weak model routes before scaling long-run work: " + ", ".join(labels))
        if not model_profiles:
            actions.append("Run a long-run or acceptance cycle to collect model capability data.")
        return list(dict.fromkeys(actions))
