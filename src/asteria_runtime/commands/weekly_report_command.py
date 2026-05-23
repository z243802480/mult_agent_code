from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from asteria_runtime.commands._runtime_os_helpers import (
    runtime_os_acceptance_evidence,
    runtime_os_catalog_report,
    runtime_os_full_summary,
    runtime_os_release_evidence,
)
from asteria_runtime.core.acceptance_catalog import enrich_acceptance_report
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class WeeklyReportResult:
    root: Path
    week_id: str
    report_path: Path
    status: str
    summary: str
    next_actions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "Weekly production report",
            f"Week: {self.week_id}",
            f"Status: {self.status}",
            f"Report: {self.report_path}",
            f"Summary: {self.summary}",
        ]
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {item}" for item in self.next_actions)
        return "\n".join(lines)


class WeeklyReportCommand:
    def __init__(
        self,
        root: Path,
        *,
        week_id: str | None = None,
        limit: int = 7,
    ) -> None:
        self.root = root.resolve()
        self.week_id = week_id or self._current_week_id()
        self.limit = limit
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> WeeklyReportResult:
        agent_dir = self.root / ".asteria"
        reports = self._long_run_reports(agent_dir)
        acceptance = self._acceptance_summary(agent_dir)
        runtime_os = self._runtime_os_summary(agent_dir)
        model_profile = self._model_profile(agent_dir)
        risk_summary = self._risk_summary(reports, acceptance, model_profile, runtime_os)
        next_actions = self._next_actions(
            reports, acceptance, model_profile, risk_summary, runtime_os
        )
        report = {
            "schema_version": "0.1.0",
            "week_id": self.week_id,
            "root": str(self.root),
            "created_at": now_iso(),
            "status": self._status(risk_summary),
            "summary": self._summary(reports, acceptance, model_profile, risk_summary),
            "long_run": self._long_run_summary(reports),
            "acceptance": acceptance,
            "runtime_os": runtime_os,
            "model_profile": model_profile,
            "risks": risk_summary,
            "next_actions": next_actions,
        }
        report_path = agent_dir / "reports" / f"weekly_report_{self.week_id}.json"
        self.store.write(report_path, report, "weekly_report")
        self._write_markdown(report_path.with_suffix(".md"), report)
        return WeeklyReportResult(
            root=self.root,
            week_id=self.week_id,
            report_path=report_path,
            status=str(report["status"]),
            summary=str(report["summary"]),
            next_actions=next_actions,
        )

    def _current_week_id(self) -> str:
        now = datetime.fromisoformat(now_iso())
        year, week, _weekday = now.isocalendar()
        return f"{year}-W{week:02d}"

    def _long_run_reports(self, agent_dir: Path) -> list[dict[str, Any]]:
        daily_dir = agent_dir / "daily"
        if not daily_dir.exists():
            return []
        reports = []
        for path in sorted(daily_dir.glob("*/daily_report.json")):
            reports.append(self.store.read(path, "daily_report"))
        return reports[-self.limit :]

    def _acceptance_summary(self, agent_dir: Path) -> dict[str, Any]:
        history_path = agent_dir / "acceptance" / "history.jsonl"
        history = self.jsonl.read_all(history_path) if history_path.exists() else []
        recent = history[-self.limit :]
        latest_path = agent_dir / "acceptance" / "acceptance_report.json"
        latest = (
            enrich_acceptance_report(self.store.read(latest_path, "acceptance_report"))
            if latest_path.exists()
            else {}
        )
        latest_source = latest or (recent[-1] if recent else {})
        aggregate = latest_source.get("aggregate") if isinstance(latest_source, dict) else {}
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        failures = []
        for scenario in latest_source.get("scenarios", []) if latest_source else []:
            if isinstance(scenario, dict) and not scenario.get("ok", False):
                failures.append(str(scenario.get("scenario") or "unknown"))
        return {
            "runs": len(recent),
            "latest_ok": bool(latest_source.get("ok")) if latest_source else None,
            "latest_suite": latest_source.get("suite") if latest_source else None,
            "latest_total": int(
                aggregate.get("total") or len(latest_source.get("scenarios", []))
                if latest_source
                else 0
            ),
            "latest_failed": int(aggregate.get("failed") or len(failures)),
            "failed_scenarios": failures[:10],
        }

    def _runtime_os_summary(self, agent_dir: Path) -> dict[str, Any]:
        latest_path = agent_dir / "acceptance" / "acceptance_report.json"
        latest = (
            enrich_acceptance_report(self.store.read(latest_path, "acceptance_report"))
            if latest_path.exists()
            else {}
        )
        scenarios = [item for item in latest.get("scenarios", []) if isinstance(item, dict)]
        required = str(latest.get("suite") or "") in {"core", "nightly"}
        evidence = runtime_os_release_evidence(self._run_dirs(agent_dir), self._read_jsonl)
        evidence.update(runtime_os_acceptance_evidence(scenarios))
        summary = runtime_os_full_summary(latest, scenarios, evidence, required=required)
        summary["catalog"] = runtime_os_catalog_report()
        return summary

    def _model_profile(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "model" / "capability_profile.json"
        if not path.exists():
            return {"status": "missing", "profile_count": 0, "weak_routes": []}
        profile = self.store.read(path, "model_capability_profile")
        weak_routes = []
        for item in profile.get("profiles", []):
            if not isinstance(item, dict):
                continue
            if int(item.get("total_calls") or 0) < 2:
                continue
            if float(item.get("success_rate") or 0.0) >= 0.8:
                continue
            weak_routes.append(
                {
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "purpose": item.get("purpose"),
                    "success_rate": item.get("success_rate"),
                    "recommended_action": item.get("recommended_action"),
                }
            )
        return {
            "status": "ready",
            "profile_count": int(profile.get("profile_count") or 0),
            "weak_routes": weak_routes[:10],
            "profile_path": str(path),
        }

    def _long_run_summary(self, reports: list[dict[str, Any]]) -> dict[str, Any]:
        attempted = sum(
            int((report.get("progress") or {}).get("attempted_actions") or 0) for report in reports
        )
        completed = sum(
            int((report.get("progress") or {}).get("completed_actions") or 0) for report in reports
        )
        failed = sum(
            int((report.get("progress") or {}).get("failed_actions") or 0) for report in reports
        )
        stopped = [
            str(report.get("stop_reason"))
            for report in reports
            if report.get("stop_reason") not in {None, "plan_only"}
        ]
        return {
            "cycles": len(reports),
            "attempted_actions": attempted,
            "completed_actions": completed,
            "failed_actions": failed,
            "stop_reasons": stopped[:10],
        }

    def _risk_summary(
        self,
        reports: list[dict[str, Any]],
        acceptance: dict[str, Any],
        model_profile: dict[str, Any],
        runtime_os: dict[str, Any],
    ) -> list[str]:
        risks = []
        if not reports:
            risks.append("No long-run cycle reports were found for this period.")
        if acceptance.get("latest_failed", 0):
            risks.append(
                "Acceptance failures remain: "
                + ", ".join(acceptance.get("failed_scenarios", [])[:5])
            )
        if model_profile.get("status") == "missing":
            risks.append("Model capability profile is missing.")
        elif model_profile.get("weak_routes"):
            labels = [
                f"{item['provider']}/{item['model']}:{item['purpose']}"
                for item in model_profile["weak_routes"][:3]
            ]
            risks.append("Weak model routes need review: " + ", ".join(labels))
        if runtime_os.get("status") in {"fail", "partial", "missing_acceptance"}:
            risks.append(f"Runtime OS release evidence is {runtime_os.get('status')}.")
        for report in reports:
            for risk in report.get("risks", [])[:3]:
                risks.append(str(risk))
        return list(dict.fromkeys(risks))[:12]

    def _status(self, risks: list[str]) -> str:
        if not risks:
            return "healthy"
        if any(
            "Acceptance failures remain" in risk or "Runtime OS release evidence is fail" in risk
            for risk in risks
        ):
            return "blocked"
        return "needs_attention"

    def _summary(
        self,
        reports: list[dict[str, Any]],
        acceptance: dict[str, Any],
        model_profile: dict[str, Any],
        risks: list[str],
    ) -> str:
        return (
            f"{len(reports)} long-run cycle(s), "
            f"{acceptance.get('runs', 0)} acceptance run(s), "
            f"{model_profile.get('profile_count', 0)} model profile(s), "
            f"{len(risks)} risk(s)."
        )

    def _next_actions(
        self,
        reports: list[dict[str, Any]],
        acceptance: dict[str, Any],
        model_profile: dict[str, Any],
        risks: list[str],
        runtime_os: dict[str, Any],
    ) -> list[str]:
        actions = []
        if not reports:
            actions.append(
                "Run `asteria /long-run-plan --objective <goal>` to start a bounded cycle."
            )
        if acceptance.get("latest_failed", 0):
            actions.append("Run `asteria /acceptance --failed-only --promote-failures`.")
        if model_profile.get("status") == "missing":
            actions.append("Run `asteria /capability-report` to generate model capability data.")
        elif model_profile.get("weak_routes"):
            actions.append("Review weak model routes before scaling long-run execution.")
        if runtime_os.get("status") in {"fail", "partial", "missing_acceptance"}:
            actions.append(
                "Run `asteria /acceptance --suite core` and `asteria /acceptance-gate --suite core`."
            )
        if not risks:
            actions.append("Continue with the next long-run cycle and keep acceptance gated.")
        return list(dict.fromkeys(actions))

    def _write_markdown(self, path: Path, report: dict[str, Any]) -> None:
        lines = [
            "# Weekly Production Report",
            "",
            f"- Week: {report['week_id']}",
            f"- Status: {report['status']}",
            f"- Summary: {report['summary']}",
            "",
            "## Long-Run",
            "",
            f"- Cycles: {report['long_run']['cycles']}",
            f"- Completed actions: {report['long_run']['completed_actions']}/{report['long_run']['attempted_actions']}",
            f"- Failed actions: {report['long_run']['failed_actions']}",
            "",
            "## Acceptance",
            "",
            f"- Latest suite: {report['acceptance'].get('latest_suite') or 'none'}",
            f"- Latest ok: {report['acceptance'].get('latest_ok')}",
            f"- Latest failed: {report['acceptance'].get('latest_failed')}",
            "",
            "## Model Profile",
            "",
            f"- Status: {report['model_profile']['status']}",
            f"- Profiles: {report['model_profile']['profile_count']}",
            "",
            "## Runtime OS",
            "",
            f"- Status: {report['runtime_os']['status']}",
            f"- Gate: {report['runtime_os']['gate'].get('status')}",
            f"- Worker results: {report['runtime_os']['evidence'].get('worker_results')}",
            f"- Acceptance worker evidence: {report['runtime_os']['evidence'].get('acceptance_worker_results_jsonl')}",
            f"- Task graph selections: {report['runtime_os']['evidence'].get('task_graph_selections')}",
            (
                "- Capability manifest audit: "
                f"{(report['runtime_os']['evidence'].get('capability_manifest_audit') or {}).get('prompt_envelopes', 0)} envelope(s), "
                f"{(report['runtime_os']['evidence'].get('capability_manifest_audit') or {}).get('model_calls_with_capability_manifest', 0)} model call(s) linked"
            ),
            f"- Candidate promotions: {report['runtime_os']['evidence'].get('candidate_promotions')} "
            f"(pending={report['runtime_os']['evidence'].get('candidate_promotions_pending')}, "
            f"blocked={report['runtime_os']['evidence'].get('candidate_promotions_blocked')}, "
            f"promoted={report['runtime_os']['evidence'].get('candidate_promotions_promoted')})",
            "",
            "## Risks",
            "",
        ]
        lines.extend(f"- {item}" for item in report["risks"])
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in report["next_actions"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run_dirs(self, agent_dir: Path) -> list[Path]:
        runs_dir = agent_dir / "runs"
        return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []

    def _read_jsonl(self, path: Path, schema_name: str | None = None) -> list[dict[str, Any]]:
        return self.jsonl.read_all(path, schema_name) if path.exists() else []
