from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands._runtime_os_helpers import runtime_os_release_evidence
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.flag_resolver import FlagResolver
from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.route_diagnostics import route_environment_for_tiers
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class GateStatusResult:
    root: Path
    stage: str
    gate_report: dict[str, Any] = field(default_factory=dict)
    gray_report: dict[str, Any] = field(default_factory=dict)
    core_report: dict[str, Any] = field(default_factory=dict)
    route_environment: dict[str, Any] = field(default_factory=dict)
    route_guidance: dict[str, Any] = field(default_factory=dict)
    promotion_release_risks: dict[str, Any] = field(default_factory=dict)
    plugin_risks: dict[str, Any] = field(default_factory=dict)
    validation_recommendation: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, Any] = field(default_factory=dict)
    capability_flags: dict[str, Any] = field(default_factory=dict)
    evidence_sources: dict[str, str] = field(default_factory=dict)
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
            "route_guidance": self.route_guidance,
            "promotion_release_risks": self.promotion_release_risks,
            "plugin_risks": self.plugin_risks,
            "feature_flags": self.feature_flags,
            "capability_flags": self.capability_flags,
            "evidence_sources": self.evidence_sources,
            "gray_task_limits": _gray_task_limits(),
            "validation_recommendation": self.validation_recommendation,
            "gate_report": self.gate_report,
            "gray_report": self.gray_report,
            "core_report": self.core_report,
            "next_actions": self.next_actions,
        }

    def _rollout_state(self) -> str:
        if self.stage in {
            "current_environment_incomplete",
            "route_guidance_blocked",
            "candidate_promotion_risk_blocked",
            "plugin_manifests_blocked",
        }:
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
        if self.route_guidance:
            lines.append(f"Route guidance: {self.route_guidance.get('status', 'unknown')}")
        if self.feature_flags:
            active = [n for n, v in self.feature_flags.items() if v.get("active")]
            lines.append(f"Feature flags: {len(active)} active of {len(self.feature_flags)}")
        if self.capability_flags:
            available = [n for n, v in self.capability_flags.items() if v.get("available")]
            lines.append(f"Capabilities: {len(available)} available of {len(self.capability_flags)}")
        if self.evidence_sources:
            lines.append("Evidence sources:")
            for name, source in sorted(self.evidence_sources.items()):
                lines.append(f"  - {name}: {source}")
        if self.promotion_release_risks:
            lines.append(
                "Promotion risks: "
                f"pending={self.promotion_release_risks.get('pending', 0)}, "
                f"blocked={self.promotion_release_risks.get('blocked', 0)}"
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
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> GateStatusResult:
        gate_path = self.root / ".asteria" / "model" / "real_model_gate_report.json"
        gate = self._read_json(gate_path)
        gray, gray_path = self._latest_acceptance_report("gray")
        core, core_path = self._latest_acceptance_report("core")
        if not core:
            fallback_core_path = self.root / ".asteria" / "acceptance" / "acceptance_report.json"
            core = self._read_json(fallback_core_path)
            core_path = fallback_core_path if core else None
        stage, actions = self._stage(gate, gray, core)
        route_environment = _route_environment()
        route_guidance = _route_guidance(self.root)
        promotion_release_risks = _promotion_release_risks(self.root, self._policy())
        if stage == "ready_for_small_real_task_gray" and not route_environment["ready"]:
            stage = "current_environment_incomplete"
            missing = ", ".join(route_environment["missing_required"])
            actions = [
                f"Set current model route environment variables before gray validation: {missing}.",
                *actions,
            ]
        if (
            stage == "ready_for_small_real_task_gray"
            and route_guidance.get("status") == "blocked"
        ):
            stage = "route_guidance_blocked"
            actions = [
                "Resolve blocked model route guidance before widening gray validation.",
                *[str(item) for item in route_guidance.get("recommended_actions", [])],
                *actions,
            ]
        if (
            stage == "ready_for_small_real_task_gray"
            and _promotion_risks_exceed_threshold(promotion_release_risks)
        ):
            stage = "candidate_promotion_risk_blocked"
            actions = [
                "Resolve release-blocking candidate promotions before gray validation.",
                "Use `asteria promotions list`, then approve, retry, reject, or discard unresolved candidates.",
                *actions,
            ]
        plugin_risks = _plugin_risks(self.root, self.validator)
        if (
            stage == "ready_for_small_real_task_gray"
            and plugin_risks["blocked"]
        ):
            stage = "plugin_manifests_blocked"
            actions = [
                *plugin_risks["actions"],
                *actions,
            ]
        policy = self._policy()
        env_capabilities = {
            "strong_model_configured": bool(route_environment.get("strong", {}).get("configured")),
            "medium_model_configured": bool(route_environment.get("medium", {}).get("configured")),
            "real_model_available": bool(gate.get("ok")),
            "provider_streaming_available": _provider_streaming_available(route_environment),
        }
        resolver = FlagResolver.from_policy(policy, env_capabilities)
        flag_results = resolver.resolve_all()
        feature_flags = {n: v for n, v in flag_results.items()}
        capability_flags = {n: c.to_dict() for n, c in resolver.capabilities.items()}

        return GateStatusResult(
            root=self.root,
            stage=stage,
            gate_report=gate,
            gray_report=gray,
            core_report=core,
            route_environment=route_environment,
            route_guidance=route_guidance,
            promotion_release_risks=promotion_release_risks,
            plugin_risks=plugin_risks,
            validation_recommendation=_validation_recommendation(self.root),
            feature_flags=feature_flags,
            capability_flags=capability_flags,
            evidence_sources=_evidence_sources(
                gate_path if gate else None,
                gray_path,
                core_path,
            ),
            next_actions=actions,
        )

    def _policy(self) -> dict[str, Any]:
        agent_dir = self.root / ".asteria"
        if not (agent_dir / "policies.json").exists():
            return {}
        return load_policy_config(agent_dir, self.validator)

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

    def _latest_acceptance_report(self, suite: str) -> tuple[dict[str, Any], Path | None]:
        verification_dir = self.root / ".asteria" / "verification"
        if not verification_dir.exists():
            return {}, None
        canonical = verification_dir / f"real_model_acceptance_{suite}.json"
        canonical_report = self._read_json(canonical)
        if _matches_acceptance_suite(canonical_report, suite) and canonical_report.get("ok"):
            return canonical_report, canonical
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        for path in verification_dir.glob(f"real_model_acceptance_{suite}*.json"):
            report = self._read_json(path)
            if _matches_acceptance_suite(report, suite):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    modified = 0.0
                candidates.append((modified, path, report))
        if not candidates:
            return {}, None
        _modified, path, report = max(candidates, key=lambda item: (item[0], item[1].name))
        return report, path


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


def _provider_streaming_available(route_environment: dict[str, Any]) -> bool:
    for tier in ("strong", "medium"):
        raw_route = route_environment.get(tier)
        route = raw_route if isinstance(raw_route, dict) else {}
        raw_streaming = route.get("streaming")
        streaming = raw_streaming if isinstance(raw_streaming, dict) else {}
        if streaming.get("enabled") is not True:
            return False
    return True


def _matches_acceptance_suite(report: dict[str, Any], suite: str) -> bool:
    if not report:
        return False
    report_suite = report.get("suite")
    if report_suite is None:
        return True
    return str(report_suite) == suite


def _evidence_sources(
    gate_path: Path | None,
    gray_path: Path | None,
    core_path: Path | None,
) -> dict[str, str]:
    sources: dict[str, str] = {}
    if gate_path is not None:
        sources["real_model_gate"] = str(gate_path)
    if gray_path is not None:
        sources["gray_suite"] = str(gray_path)
    if core_path is not None:
        sources["core_acceptance"] = str(core_path)
    return sources


def _route_guidance(root: Path) -> dict[str, Any]:
    validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
    return CapabilityFeedbackAdvisor(validator).route_guidance(root / ".asteria")


def _promotion_release_risks(root: Path, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
    evidence = runtime_os_release_evidence(_run_dirs(root), JsonlStore(validator).read_all)
    risk_policy = _promotion_risk_policy(policy or {})
    return {
        "total": int(evidence.get("candidate_promotions") or 0),
        "pending": int(evidence.get("candidate_promotions_pending") or 0),
        "blocked": int(evidence.get("candidate_promotions_blocked") or 0),
        "promoted": int(evidence.get("candidate_promotions_promoted") or 0),
        "risk_policy": risk_policy,
        "release_blocking_threshold": max(
            int(risk_policy["max_pending_release_promotions"]),
            int(risk_policy["max_blocked_release_promotions"]),
        ),
        "release_blocking_statuses": list(risk_policy["release_blocking_statuses"]),
    }


def _promotion_risk_policy(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("promotion")
    promotion = raw if isinstance(raw, dict) else {}
    return {
        "manual_approval_default": bool(promotion.get("manual_approval_default", False)),
        "release_blocking_statuses": list(
            promotion.get("release_blocking_statuses")
            or [
                "queued",
                "pending_manual_approval",
                "approved",
                "blocked",
                "promotion_failed",
            ]
        ),
        "max_pending_release_promotions": int(
            promotion.get("max_pending_release_promotions", 0)
        ),
        "max_blocked_release_promotions": int(
            promotion.get("max_blocked_release_promotions", 0)
        ),
    }


def _promotion_risks_exceed_threshold(risks: dict[str, Any]) -> bool:
    raw_policy = risks.get("risk_policy")
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    max_pending = int(policy.get("max_pending_release_promotions", 0))
    max_blocked = int(policy.get("max_blocked_release_promotions", 0))
    return int(risks.get("pending", 0)) > max_pending or int(risks.get("blocked", 0)) > max_blocked


def _run_dirs(root: Path) -> list[Path]:
    runs_dir = root / ".asteria" / "runs"
    return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []


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
    governance_changes = [
        path
        for path in changed_files
        if path.startswith(("schemas/", "templates/"))
        or "plugin_manifest" in path
        or "runtime_hook" in path
        or "policy_config" in path
        or "policies.default" in path
    ]
    if governance_changes:
        return {
            "level": "full_gray_core",
            "reason": "Schema, policy, or hook/plugin governance files changed.",
            "changed_file_count": len(changed_files),
            "governance_changes": governance_changes,
            "command": (
                "ruff check . && mypy src && pytest -q && "
                "asteria package-check --root . --json && "
                "asteria /acceptance-gate --suite core"
            ),
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

def _plugin_risks(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    try:
        summary = plugin_control_summary(root, validator)
    except (FileNotFoundError, OSError, ValueError):
        return {"blocked": False, "warnings": [], "actions": [], "plugin_control": {}}
    if not summary.get("initialized", False):
        return {"blocked": False, "warnings": [], "actions": [], "plugin_control": summary}
    blocked_ids = [
        str(p.get("plugin_id", "?"))
        for p in summary.get("plugins", [])
        if p.get("status") == "blocked"
    ]
    warnings = list(summary.get("warnings") or [])
    actions: list[str] = []
    if blocked_ids:
        actions.append(f"Blocked plugin manifests prevent release: {', '.join(blocked_ids)}.")
        actions.append("Run steria plugins doctor --json and fix or disable blocked manifests.")
    if not summary.get("ok", True):
        actions.append("Plugin control surface reports issues; resolve before release.")
    return {
        "blocked": len(blocked_ids) > 0,
        "blocked_manifests": blocked_ids,
        "warnings": warnings,
        "actions": actions,
        "plugin_control": summary,
    }
