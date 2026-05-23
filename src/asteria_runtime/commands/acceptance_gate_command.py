from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.acceptance.runtime_os_gate import RuntimeOSGateEvaluator
from asteria_runtime.commands._runtime_os_helpers import (
    runtime_os_catalog_report,
    runtime_os_release_evidence,
)
from asteria_runtime.commands.acceptance_history_command import AcceptanceHistoryCommand
from asteria_runtime.core.acceptance_catalog import (
    acceptance_metadata_index,
    enrich_acceptance_report,
    enrich_acceptance_scenario,
)
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


RELEASE_BLOCKING_PROMOTION_STATUSES = [
    "queued",
    "pending_manual_approval",
    "approved",
    "blocked",
    "promotion_failed",
]


@dataclass(frozen=True)
class AcceptanceGateResult:
    ok: bool
    report_path: Path
    suite: str
    scenario_count: int
    passed_count: int
    failed_count: int
    release_status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    runtime_os: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        lines = [
            "Acceptance gate",
            f"Status: {'pass' if self.ok else 'fail'}",
            f"Release status: {self.release_status}",
            f"Report: {self.report_path}",
            f"Suite: {self.suite}",
            f"Scenarios: {self.passed_count}/{self.scenario_count} passed, failed={self.failed_count}",
        ]
        if self.failures:
            lines.append("Failures:")
            lines.extend(f"  - {failure}" for failure in self.failures)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        if self.runtime_os:
            lines.append("Runtime OS gate:")
            lines.append(f"  status: {self.runtime_os.get('status', 'unknown')}")
            lines.append(
                "  coverage: "
                + ", ".join(self.runtime_os.get("covered_capabilities", []) or ["none"])
            )
            missing = self.runtime_os.get("missing_capabilities", [])
            if missing:
                lines.append("  missing: " + ", ".join(missing))
            missing_evidence = self.runtime_os.get("missing_evidence", [])
            if missing_evidence:
                lines.append("  missing evidence:")
                lines.extend(f"    - {item}" for item in missing_evidence)
            manifest_audit = self.runtime_os.get("capability_manifest_audit") or {}
            if manifest_audit:
                lines.append(
                    "  capability manifest audit: "
                    f"{manifest_audit.get('model_calls_with_capability_manifest', 0)} "
                    "model call(s) linked"
                )
                if manifest_audit.get("manifest_changed"):
                    lines.append("  manifest changed: true")
        if self.next_actions:
            lines.append("Recommended next actions:")
            lines.extend(f"  - {action}" for action in self.next_actions)
        return "\n".join(lines)


class AcceptanceGateCommand:
    def __init__(
        self,
        root: Path,
        report_path: Path | None = None,
        suite: str | None = None,
        min_scenarios: int = 1,
        min_capabilities: int | None = None,
        require_tiers: list[str] | None = None,
        allow_trend_warnings: bool = False,
        require_repair_closure: bool = True,
        require_runtime_os: bool | None = None,
    ) -> None:
        self.root = root.resolve()
        self.report_path = report_path
        self.suite = suite
        self.min_scenarios = min_scenarios
        self.min_capabilities = min_capabilities
        self.require_tiers = require_tiers
        self.allow_trend_warnings = allow_trend_warnings
        self.require_repair_closure = require_repair_closure
        self.require_runtime_os = require_runtime_os
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> AcceptanceGateResult:
        report_path = (
            self.report_path.resolve()
            if self.report_path
            else self.root / ".asteria" / "acceptance" / "acceptance_report.json"
        )
        if not report_path.exists():
            return self._missing_report(report_path)

        report = enrich_acceptance_report(self.store.read(report_path, "acceptance_report"))
        failures: list[str] = []
        warnings: list[str] = []
        next_actions: list[str] = []

        suite = str(report.get("suite") or "unknown")
        if self.suite and suite != self.suite:
            failures.append(f"expected suite {self.suite!r}, found {suite!r}")

        scenarios = [item for item in report.get("scenarios", []) if isinstance(item, dict)]
        scenario_count = len(scenarios)
        closed_failures = self._closed_failures(report)
        passed_count = len(
            [
                scenario
                for scenario in scenarios
                if scenario.get("ok") or str(scenario.get("scenario") or "") in closed_failures
            ]
        )
        failed = [
            scenario
            for scenario in scenarios
            if not scenario.get("ok") and str(scenario.get("scenario") or "") not in closed_failures
        ]
        failed_count = len(failed)
        if scenario_count < self.min_scenarios:
            failures.append(
                f"scenario count {scenario_count} is below required minimum {self.min_scenarios}"
            )
        capability_count, missing_tiers = self._coverage(report, scenarios)
        required_capabilities = self.min_capabilities
        if required_capabilities is None:
            required_capabilities = self._default_min_capabilities(suite)
        if capability_count < required_capabilities:
            failures.append(
                f"capability coverage {capability_count} is below required minimum "
                f"{required_capabilities}"
            )
            next_actions.append(
                "Run a broader acceptance suite with multi-file, config, repair, docs, and refactor scenarios."
            )
        if missing_tiers:
            failures.append("missing required acceptance tiers: " + ", ".join(missing_tiers))
            next_actions.append("Run scenarios from the missing tiers before release.")

        if not report.get("ok", False):
            closure = self._dict(report.get("repair_closure"))
            closure_ok = closure.get("rerun_ok") is True and not closure.get(
                "remaining_failures", []
            )
            if self.require_repair_closure and not closure_ok:
                failures.append("acceptance failed and repair closure did not prove recovery")
                next_actions.append(
                    "Run `asteria /acceptance --promote-failures --rerun-promoted` after fixing failures."
                )
            elif closure_ok:
                warnings.append(
                    "base acceptance failed, but promoted repair rerun closed the failures"
                )
        if failed:
            names = ", ".join(str(scenario.get("scenario") or "unknown") for scenario in failed)
            next_actions.append(f"Inspect failed scenario evidence and repair: {names}")

        trend_warnings = [str(item) for item in report.get("trend_warnings", [])]
        history_warnings = (
            AcceptanceHistoryCommand(
                self.root,
                limit=1,
                suite=suite,
                history_jsonl=self.root / ".asteria" / "acceptance" / "history.jsonl",
            )
            .run()
            .warnings
        )
        blocking_trend_warnings = list(dict.fromkeys([*trend_warnings, *history_warnings]))
        if closed_failures:
            blocking_trend_warnings = [
                warning for warning in blocking_trend_warnings if "failed scenario" not in warning
            ]
        warnings.extend(blocking_trend_warnings)
        if blocking_trend_warnings and not self.allow_trend_warnings:
            failures.append("acceptance trend warnings are present")
            next_actions.append(
                "Review `asteria /acceptance-history` and rerun acceptance after reducing regressions."
            )

        runtime_os = self._runtime_os_gate(report, scenarios)
        if runtime_os["required"] and runtime_os["status"] != "pass":
            failures.append("runtime OS acceptance evidence is incomplete")
            next_actions.append(
                "Run core acceptance with runtime OS scenarios, then rerun `asteria /acceptance-gate`."
            )
        promotion_risks = self._promotion_release_risks()
        runtime_os["promotion_release_risks"] = promotion_risks
        release_evidence = runtime_os_release_evidence(self._run_dirs(), self._read_jsonl)
        runtime_os["capability_manifest_audit"] = release_evidence.get(
            "capability_manifest_audit", {}
        )
        runtime_os["catalog"] = runtime_os_catalog_report()
        if promotion_risks["pending"] or promotion_risks["blocked"]:
            failures.append("candidate promotion queue has unresolved release risks")
            next_actions.append(
                "Resolve release-blocking candidate promotions before release: "
                "`asteria promotions list --status pending_manual_approval`, "
                "`asteria promotions approve --all-pending`, `asteria promotions retry`, "
                "or `asteria promotions discard`."
            )

        ok = not failures
        release_status = self._release_status(ok, report, warnings)
        return AcceptanceGateResult(
            ok=ok,
            report_path=report_path,
            suite=suite,
            scenario_count=scenario_count,
            passed_count=passed_count,
            failed_count=failed_count,
            release_status=release_status,
            failures=list(dict.fromkeys(failures)),
            warnings=list(dict.fromkeys(warnings)),
            next_actions=list(dict.fromkeys(next_actions)),
            runtime_os=runtime_os,
        )

    def _missing_report(self, report_path: Path) -> AcceptanceGateResult:
        return AcceptanceGateResult(
            ok=False,
            report_path=report_path,
            suite=self.suite or "unknown",
            scenario_count=0,
            passed_count=0,
            failed_count=0,
            release_status="blocked",
            failures=[f"acceptance report not found: {report_path}"],
            next_actions=["Run `asteria /acceptance --suite core` before release."],
            runtime_os={"required": False, "status": "missing_report"},
        )

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _release_status(self, ok: bool, report: dict, warnings: list[str]) -> str:
        if not ok:
            return "blocked"
        if warnings or report.get("repair_closure"):
            return "conditional"
        return "ready"

    def _coverage(self, report: dict, scenarios: list[dict]) -> tuple[int, list[str]]:
        metadata = acceptance_metadata_index(report)
        closed_failures = self._closed_failures(report)
        passed_capabilities = set()
        present_tiers = set()
        for scenario in scenarios:
            scenario = enrich_acceptance_scenario(scenario, metadata)
            capability = scenario.get("capability")
            tier = scenario.get("tier")
            if tier:
                present_tiers.add(str(tier))
            scenario_name = str(scenario.get("scenario") or "")
            if (scenario.get("ok") or scenario_name in closed_failures) and capability:
                passed_capabilities.add(str(capability))
        required_tiers = (
            self.require_tiers
            if self.require_tiers is not None
            else self._default_required_tiers(str(report.get("suite")))
        )
        missing_tiers = [tier for tier in required_tiers if tier not in present_tiers]
        return len(passed_capabilities), missing_tiers

    def _closed_failures(self, report: dict) -> set[str]:
        closure = self._dict(report.get("repair_closure"))
        if closure.get("rerun_ok") is not True or closure.get("remaining_failures"):
            return set()
        return {str(item) for item in closure.get("closed_failures", [])}

    def _default_min_capabilities(self, suite: str) -> int:
        return {
            "smoke": 1,
            "offline": 1,
            "core": 5,
            "advanced": 4,
            "nightly": 8,
        }.get(suite, 1)

    def _default_required_tiers(self, suite: str) -> list[str]:
        if suite == "nightly":
            return ["smoke", "core", "advanced"]
        if suite == "advanced":
            return ["advanced"]
        if suite == "core":
            return ["smoke", "core"]
        return []

    def _runtime_os_gate(self, report: dict, scenarios: list[dict]) -> dict[str, Any]:
        suite = str(report.get("suite") or "")
        required = (
            self.require_runtime_os
            if self.require_runtime_os is not None
            else suite in {"core", "nightly"}
        )
        return RuntimeOSGateEvaluator().evaluate(report, scenarios, required=required).to_dict()

    def _promotion_release_risks(self) -> dict[str, Any]:
        evidence = runtime_os_release_evidence(self._run_dirs(), self._read_jsonl)
        return {
            "total": int(evidence.get("candidate_promotions") or 0),
            "pending": int(evidence.get("candidate_promotions_pending") or 0),
            "blocked": int(evidence.get("candidate_promotions_blocked") or 0),
            "promoted": int(evidence.get("candidate_promotions_promoted") or 0),
            "release_blocking_threshold": 0,
            "release_blocking_statuses": RELEASE_BLOCKING_PROMOTION_STATUSES,
        }

    def _run_dirs(self) -> list[Path]:
        runs_dir = self.root / ".asteria" / "runs"
        return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []

    def _read_jsonl(self, path: Path, schema_name: str | None = None) -> list[dict[str, Any]]:
        return JsonlStore(self.validator).read_all(path, schema_name) if path.exists() else []
