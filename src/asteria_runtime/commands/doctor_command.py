from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.core.access_profile import (
    BUILTIN_ACCESS_PROFILES,
    access_profile_summary,
    apply_access_profile,
)
from asteria_runtime.core.error_taxonomy import classify_check, taxonomy_summary
from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.core.policy_config import merge_policy_defaults
from asteria_runtime.models.route_diagnostics import (
    route_diagnostic_for_tier,
    route_requirement_names,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    summary: str
    severity: str = "info"
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "severity": self.severity,
            "error_type": self.error_type or classify_check(self.name),
        }


@dataclass(frozen=True)
class DoctorResult:
    root: Path
    checks: list[DoctorCheck] = field(default_factory=list)
    routes: dict[str, dict[str, object]] = field(default_factory=dict)
    sandbox: dict[str, object] = field(default_factory=dict)
    route_requirements: dict[str, list[str]] = field(default_factory=dict)
    validation_task_limits: dict[str, object] = field(default_factory=dict)
    plugin_control: dict[str, object] = field(default_factory=dict)
    access_profile: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(check.severity == "error" and not check.ok for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        failed = [check.name for check in self.checks if not check.ok]
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="doctor",
                audience="maintainer_preflight",
                stable_fields=[
                    "schema_version",
                    "root",
                    "ok",
                    "status",
                    "summary",
                    "checks",
                    "failed_checks",
                    "routes",
                    "route_requirements",
                    "sandbox",
                    "access_profile",
                    "validation_task_limits",
                    "plugin_control",
                    "error_taxonomy",
                    "next_actions",
                ],
            ),
            "root": str(self.root),
            "ok": self.ok,
            "status": "pass" if self.ok else "fail",
            "summary": "Doctor checks passed." if self.ok else "Doctor found blocking issues.",
            "checks": [check.to_dict() for check in self.checks],
            "failed_checks": failed,
            "routes": self.routes,
            "route_requirements": self.route_requirements,
            "sandbox": self.sandbox,
            "access_profile": self.access_profile,
            "validation_task_limits": self.validation_task_limits,
            "plugin_control": self.plugin_control,
            "error_taxonomy": taxonomy_summary(),
            "next_actions": self._next_actions(failed),
        }

    def _next_actions(self, failed: list[str]) -> list[str]:
        actions = []
        if "agent_dir" in failed:
            actions.append("Run `asteria /init --root .`.")
        missing_routes = [
            name.replace("model_", "") for name in failed if name.startswith("model_")
        ]
        for tier in missing_routes:
            route = self.routes.get(tier, {})
            raw_missing = route.get("missing")
            missing = raw_missing if isinstance(raw_missing, list) else []
            required_names = [str(name) for name in missing] or self.route_requirements.get(
                tier, []
            )
            required = ", ".join(required_names)
            actions.append(
                f"Set {tier} route environment variables before validation: {required}."
            )
        if "real_model_gate" in failed:
            actions.append(
                "Run `asteria real-model-gate --summary-json .asteria/model/real_model_gate_report.json`."
            )
        if "plugins" in failed:
            actions.append("Run `asteria plugins doctor --root . --json` and fix blocked manifests.")
        actions.append(
            "Use `docs/zh/验证试运行手册.md` for install self-check, upgrade, rollback, failure collection, and pause/resume."
        )
        return actions

    def _access_profile_text(self) -> str:
        profile = self.access_profile or {}
        if profile.get("initialized") is False:
            return "unknown (workspace not initialized)"
        active = profile.get("active")
        shell = "on" if profile.get("shell_enabled") else "off"
        network = "on" if profile.get("network_enabled") else "off"
        if active:
            return f"{active} (shell {shell}, network {network})"
        return (
            f"none (shell {shell}, network {network}); "
            "set active_access_profile in .asteria/policies.json to restrict"
        )

    def to_text(self) -> str:
        lines = [
            "Agent doctor",
            f"Root: {self.root}",
            f"Status: {'pass' if self.ok else 'fail'}",
            f"Access profile: {self._access_profile_text()}",
            "Checks:",
        ]
        for check in self.checks:
            marker = "ok" if check.ok else check.severity
            lines.append(f"  - {check.name}: {marker} - {check.summary}")
        if not self.ok:
            failed = [check.name for check in self.checks if not check.ok]
            actions = self._next_actions(failed)
            if actions:
                lines.append("Next actions:")
                lines.extend(f"  - {item}" for item in actions)
            else:
                lines.append("Next: fix error checks before running validation.")
        return "\n".join(lines)


class DoctorCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> DoctorResult:
        route_checks = [self._model_route_check("strong"), self._model_route_check("medium")]
        plugin_control = plugin_control_summary(self.root, self.validator)
        return DoctorResult(
            root=self.root,
            checks=[
                self._agent_dir_check(),
                self._agents_guidance_check(),
                self._policy_check(),
                self._plugins_check(plugin_control),
                self._git_check(),
                *route_checks,
                self._gate_report_check(),
            ],
            routes={tier: self._route_summary(tier) for tier in ["strong", "medium", "cheap"]},
            route_requirements={
                tier: self._route_requirement_names(tier) for tier in ["strong", "medium", "cheap"]
            },
            sandbox=self._sandbox_summary(),
            access_profile=self._access_profile_summary(),
            validation_task_limits=_validation_task_limits(),
            plugin_control=plugin_control,
        )

    def _access_profile_summary(self) -> dict[str, object]:
        path = self.root / ".asteria" / "policies.json"
        if not path.exists():
            return {
                "active": None,
                "available": sorted(BUILTIN_ACCESS_PROFILES),
                "shell_enabled": None,
                "network_enabled": None,
                "initialized": False,
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        # Resolve without side effects: merge defaults + overlay the active profile
        # in memory only (never write back from a read-only diagnostic).
        resolved = apply_access_profile(merge_policy_defaults(raw))
        summary = access_profile_summary(resolved)
        summary["initialized"] = True
        return summary

    def _agent_dir_check(self) -> DoctorCheck:
        path = self.root / ".asteria"
        return DoctorCheck(
            "agent_dir",
            path.exists(),
            ".asteria exists" if path.exists() else "workspace is not initialized",
            "error",
        )

    def _agents_guidance_check(self) -> DoctorCheck:
        path = self.root / "AGENTS.md"
        return DoctorCheck(
            "root_guidance",
            path.exists(),
            "AGENTS.md exists" if path.exists() else "AGENTS.md missing",
            "error",
        )

    def _policy_check(self) -> DoctorCheck:
        required = [
            self.root / ".asteria" / "project.json",
            self.root / ".asteria" / "policies.json",
        ]
        missing = [path.name for path in required if not path.exists()]
        return DoctorCheck(
            "runtime_config",
            not missing,
            "project and policy config present"
            if not missing
            else "missing: " + ", ".join(missing),
            "error",
        )

    def _git_check(self) -> DoctorCheck:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return DoctorCheck("git", False, f"git unavailable: {exc}", "warning")
        ok = completed.returncode == 0 and completed.stdout.strip() == "true"
        return DoctorCheck(
            "git",
            ok,
            "git worktree detected" if ok else "no git worktree; sandbox falls back to temp copy",
            "warning",
        )

    def _plugins_check(self, plugin_control: dict[str, object]) -> DoctorCheck:
        if plugin_control.get("initialized") is False:
            return DoctorCheck("plugins", True, "workspace is not initialized", "info")
        ok = bool(plugin_control.get("ok", True))
        summary = str(plugin_control.get("summary") or "plugin control surface unavailable")
        warnings = plugin_control.get("warnings")
        if isinstance(warnings, list) and warnings:
            summary += "; " + "; ".join(str(item) for item in warnings)
        return DoctorCheck("plugins", ok, summary, "warning")

    def _model_route_check(self, tier: str) -> DoctorCheck:
        diagnostic = route_diagnostic_for_tier(tier)
        if not diagnostic.configured:
            return DoctorCheck(
                f"model_{tier}",
                False,
                "missing: " + ", ".join(diagnostic.missing),
                "warning",
            )
        if diagnostic.returns_canned_output:
            # ADR-0016 §3 honesty: the tier resolves to the fake/offline provider, which fabricates
            # output. It IS runnable (offline is intentional) so this is not an error, but never
            # present it as a real model — warn so the canned output is never mistaken for a run.
            return DoctorCheck(
                f"model_{tier}",
                True,
                f"{diagnostic.provider}/{diagnostic.model_name or 'model not set'} "
                "returns CANNED placeholder output (not a real model); set "
                f"AGENT_MODEL_{tier.upper()}_PROVIDER (or AGENT_MODEL_PROVIDER) to a real "
                "provider for real output",
                "warning",
            )
        return DoctorCheck(
            f"model_{tier}",
            True,
            f"{diagnostic.provider}/{diagnostic.model_name or 'model not set'} "
            f"at {diagnostic.base_url or 'base url not set'} "
            f"via {diagnostic.source}",
            "info",
        )

    def _route_summary(self, tier: str) -> dict[str, object]:
        return route_diagnostic_for_tier(tier).to_dict()

    def _route_requirement_names(self, tier: str) -> list[str]:
        return route_requirement_names(tier)

    def _sandbox_summary(self) -> dict[str, object]:
        git = self._git_available()
        tracked_clean = self._tracked_git_clean() if git else False
        backend = "git_worktree" if git and tracked_clean else "temp_workspace"
        return {
            "git_available": git,
            "tracked_worktree_clean": tracked_clean,
            "preferred_backend": backend,
            "fallback_backend": "temp_workspace",
            "reason": (
                "tracked git state supports worktree candidate branches"
                if backend == "git_worktree"
                else "git unavailable or tracked files are dirty; use copied temp workspace"
            ),
        }

    def _git_available(self) -> bool:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and completed.stdout.strip() == "true"

    def _tracked_git_clean(self) -> bool:
        try:
            completed = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and not completed.stdout.strip()

    def _gate_report_check(self) -> DoctorCheck:
        path = self.root / ".asteria" / "model" / "real_model_gate_report.json"
        return DoctorCheck(
            "real_model_gate",
            path.exists(),
            str(path) if path.exists() else "real model gate report missing",
            "warning",
        )


def _validation_task_limits() -> dict[str, object]:
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
        "allowed_task_types": [
            "file_artifact",
            "small_cli_or_script",
            "multi_file_small_tool",
            "test_repair",
            "controlled_refactor",
            "documentation_update",
        ],
        "stop_conditions": [
            "cost_status near_limit or hard_stop",
            "repeated schema-invalid provider responses",
            "merge gate promotion risk",
            "protected path risk",
            "session cannot resume",
        ],
    }
