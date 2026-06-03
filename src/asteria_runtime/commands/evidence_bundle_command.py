from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime import __version__
from asteria_runtime.utils.time import now_iso


SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
PROTECTED_PARTS = {
    ".git",
    ".env",
    "secrets",
    "model.routes.local.ps1",
    "model.routes.local.json",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|authorization|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,}]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
]


@dataclass(frozen=True)
class EvidenceBundleResult:
    root: Path
    bundle_path: Path
    manifest_path: Path
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rolling_validation_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.bundle_path.exists() and self.manifest_path.exists()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "ok": self.ok,
            "status": "pass" if self.ok else "fail",
            "root": str(self.root),
            "bundle_path": str(self.bundle_path),
            "manifest_path": str(self.manifest_path),
            "files": self.files,
            "warnings": self.warnings,
            "v0_2_rolling_validation": {
                "status": self.rolling_validation_summary.get("status"),
                "sample_count": self.rolling_validation_summary.get("sample_count"),
                "matrix_summary_count": self.rolling_validation_summary.get(
                    "matrix_summary_count"
                ),
                "coverage": self.rolling_validation_summary.get("coverage"),
                "next_actions": self.rolling_validation_summary.get("next_actions"),
            },
            "redaction": {
                "protected_paths_excluded": sorted(PROTECTED_PARTS),
                "secret_keys_redacted": sorted(SECRET_KEYS),
            },
            "next_actions": [
                "Share the bundle with the maintainer for post-run analysis.",
                "Keep local route/API key files outside the bundle.",
            ],
        }

    def to_text(self) -> str:
        lines = [
            "Evidence bundle",
            f"Root: {self.root}",
            f"Status: {'pass' if self.ok else 'fail'}",
            f"Bundle: {self.bundle_path}",
            f"Manifest: {self.manifest_path}",
            f"Files: {len(self.files)}",
        ]
        if self.rolling_validation_summary:
            lines.append(
                "v0.2 rolling validation: "
                f"{self.rolling_validation_summary.get('status', 'unknown')} "
                f"({self.rolling_validation_summary.get('sample_count', 0)} sample(s))"
            )
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        lines.append("Protected route/API key files were excluded.")
        return "\n".join(lines)


class EvidenceBundleCommand:
    def __init__(
        self,
        root: Path,
        output: Path | None = None,
        *,
        include_events: bool = True,
        include_model_calls: bool = True,
        max_runs: int = 12,
    ) -> None:
        self.root = root.resolve()
        self.agent_dir = self.root / ".asteria"
        self.output = output
        self.include_events = include_events
        self.include_model_calls = include_model_calls
        self.max_runs = max(1, max_runs)

    def run(self) -> EvidenceBundleResult:
        bundle_dir = self.agent_dir / "evidence_bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_iso().replace(":", "").replace("+", "-").replace("T", "T")
        bundle_path = (self.output or bundle_dir / f"evidence-{stamp}.zip").resolve()
        manifest_path = bundle_path.with_suffix(".manifest.json")
        staging: dict[str, str] = {}
        warnings: list[str] = []

        if not self.agent_dir.exists():
            warnings.append(".asteria directory is missing; bundle contains environment only.")

        rolling_validation = self._rolling_validation_summary()
        manifest = self._manifest(warnings, rolling_validation)
        staging["manifest.json"] = _json_text(manifest)
        staging["v0.2_rolling_validation_summary.json"] = _json_text(_redact(rolling_validation))
        self._add_summary_files(staging, warnings)
        self._add_validation_run_summaries(staging, warnings)
        self._add_ops_signal_files(staging, warnings)
        self._add_recent_runs(staging, warnings)

        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, text in sorted(staging.items()):
                archive.writestr(name, text)
        manifest_path.write_text(_json_text(manifest), encoding="utf-8")

        return EvidenceBundleResult(
            root=self.root,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            files=sorted(staging),
            warnings=warnings,
            rolling_validation_summary=rolling_validation,
        )

    def _manifest(
        self,
        warnings: list[str],
        rolling_validation: dict[str, Any],
    ) -> dict[str, Any]:
        model_calls = self._all_model_calls()
        by_route: dict[str, dict[str, Any]] = {}
        for call in model_calls:
            route = "/".join(
                [
                    str(call.get("model_provider") or "unknown"),
                    str(call.get("model_name") or "unknown"),
                    str(call.get("purpose") or "unknown"),
                    str(call.get("model_tier") or "unknown"),
                ]
            )
            item = by_route.setdefault(
                route,
                {
                    "total": 0,
                    "success": 0,
                    "failure": 0,
                    "streaming_failed": 0,
                    "first_chunk_ms_values": [],
                    "duration_ms_values": [],
                },
            )
            item["total"] += 1
            if call.get("status") == "success":
                item["success"] += 1
            elif call.get("status") == "failure":
                item["failure"] += 1
            raw_streaming = call.get("streaming")
            streaming: dict[str, Any] = raw_streaming if isinstance(raw_streaming, dict) else {}
            if streaming.get("mode") == "streaming_failed":
                item["streaming_failed"] += 1
            for source_key, target_key in (
                ("first_chunk_ms", "first_chunk_ms_values"),
                ("duration_ms", "duration_ms_values"),
            ):
                value = streaming.get(source_key) or call.get(source_key)
                if isinstance(value, int | float):
                    item[target_key].append(int(value))

        route_summary = {}
        for route, item in by_route.items():
            route_summary[route] = {
                "total": item["total"],
                "success": item["success"],
                "failure": item["failure"],
                "streaming_failed": item["streaming_failed"],
                "success_rate": round(item["success"] / item["total"], 4) if item["total"] else 0.0,
                "first_chunk_ms_p50": _percentile(item["first_chunk_ms_values"], 0.5),
                "first_chunk_ms_p95": _percentile(item["first_chunk_ms_values"], 0.95),
                "duration_ms_p50": _percentile(item["duration_ms_values"], 0.5),
                "duration_ms_p95": _percentile(item["duration_ms_values"], 0.95),
            }

        return {
            "schema_version": "0.1.0",
            "created_at": now_iso(),
            "root": str(self.root),
            "asteria_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "network_environment": {
                "user_reported": "unknown",
                "notes": "Record whether this run used VPN, proxy, or domestic provider access outside the bundle.",
            },
            "completion_assessment": {
                "runtime_os_alpha": "implemented enough for controlled alpha dogfooding",
                "release_gate": "requires gate-status evidence from target environment",
                "not_done": [
                    "large-batch real task scaling requires healthy route guidance",
                    "candidate worktree/manual promotion default still needs DecisionPoint",
                    "operator UX should continue improving progress and evidence review",
                ],
            },
            "model_route_summary": route_summary,
            "included_evidence": {
                "summary_files": True,
                "validation_runs": True,
                "ops_signals": True,
                "recent_runs": True,
                "v0_2_rolling_validation": True,
            },
            "v0_2_rolling_validation": {
                "status": rolling_validation.get("status"),
                "sample_count": rolling_validation.get("sample_count"),
                "matrix_summary_count": rolling_validation.get("matrix_summary_count"),
                "required_sample_range": rolling_validation.get("required_sample_range"),
                "coverage": rolling_validation.get("coverage"),
                "next_actions": rolling_validation.get("next_actions"),
            },
            "warnings": warnings,
        }

    def _add_summary_files(self, staging: dict[str, str], warnings: list[str]) -> None:
        candidates = [
            self.agent_dir / "model" / "real_model_gate_report.json",
            self.agent_dir / "model" / "real_model_smoke_summary.json",
            self.agent_dir / "model" / "capability_profile.json",
            self.agent_dir / "verification" / "real_model_acceptance_validation.json",
            self.agent_dir / "verification" / "real_model_acceptance_core.json",
            self.agent_dir / "verification" / "acceptance_report_core.json",
            self.agent_dir / "verification" / "acceptance_gate_core.json",
        ]
        for path in candidates:
            self._stage_file(path, staging, warnings)

    def _add_validation_run_summaries(
        self,
        staging: dict[str, str],
        warnings: list[str],
    ) -> None:
        validation_dir = self.agent_dir / "validation_runs"
        if not validation_dir.exists():
            return
        root_summaries = sorted(
            (path for path in validation_dir.glob("*.json") if path.is_file()),
            reverse=True,
        )[: self.max_runs]
        for summary_path in root_summaries:
            self._stage_file(summary_path, staging, warnings)
        runs = sorted(
            (path for path in validation_dir.iterdir() if path.is_dir()),
            reverse=True,
        )[: self.max_runs]
        for run_dir in runs:
            self._stage_file(run_dir / "summary.json", staging, warnings)

    def _add_ops_signal_files(self, staging: dict[str, str], warnings: list[str]) -> None:
        ops_dir = self.agent_dir / "ops"
        self._stage_jsonl_tail(ops_dir / "usage_signals.jsonl", staging, warnings, limit=250)
        self._stage_file(ops_dir / "usage_signal_analysis.json", staging, warnings)

    def _add_recent_runs(self, staging: dict[str, str], warnings: list[str]) -> None:
        runs_dir = self.agent_dir / "runs"
        if not runs_dir.exists():
            return
        runs = sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True)[
            : self.max_runs
        ]
        for run_dir in runs:
            self._stage_file(run_dir / "run.json", staging, warnings)
            self._stage_file(run_dir / "cost_report.json", staging, warnings)
            if self.include_events:
                self._stage_jsonl_tail(run_dir / "events.jsonl", staging, warnings, limit=250)
            if self.include_model_calls:
                self._stage_jsonl_tail(run_dir / "model_calls.jsonl", staging, warnings, limit=250)
            self._stage_jsonl_tail(run_dir / "workers.jsonl", staging, warnings, limit=250)
            self._stage_jsonl_tail(
                run_dir / "task_execution_evidence.jsonl", staging, warnings, limit=250
            )
            self._stage_jsonl_tail(run_dir / "worker_results.jsonl", staging, warnings, limit=250)
            self._stage_jsonl_tail(
                run_dir / "validation_results.jsonl", staging, warnings, limit=250
            )
            self._stage_jsonl_tail(
                run_dir / "context_budget_snapshots.jsonl",
                staging,
                warnings,
                limit=250,
            )
            self._stage_jsonl_tail(
                run_dir / "capability_decisions.jsonl",
                staging,
                warnings,
                limit=250,
            )
            self._stage_jsonl_tail(
                run_dir / "agent_loop_decisions.jsonl",
                staging,
                warnings,
                limit=250,
            )
            self._stage_jsonl_tail(
                run_dir / "agent_loop_execution_results.jsonl",
                staging,
                warnings,
                limit=250,
            )
            self._stage_jsonl_tail(
                run_dir / "agent_loop_observations.jsonl",
                staging,
                warnings,
                limit=250,
            )
            self._stage_file(run_dir / "agent_loop_run_summary.json", staging, warnings)
            self._stage_file(run_dir / "agent_run_graph.json", staging, warnings)

    def _rolling_validation_summary(self) -> dict[str, Any]:
        runs_dir = self.agent_dir / "runs"
        run_dirs = (
            sorted(
                (
                    path
                    for path in runs_dir.iterdir()
                    if path.is_dir() and path.name.startswith("run-")
                ),
                key=_run_dir_sort_key,
                reverse=True,
            )[: self.max_runs]
            if runs_dir.exists()
            else []
        )
        samples = [self._rolling_validation_sample(run_dir) for run_dir in run_dirs]
        samples = [sample for sample in samples if sample["evidence"]["has_any_runtime_evidence"]]
        samples = samples[:5]
        matrix_summaries = self._rolling_matrix_summaries()
        coverage = {
            "route": any(sample["evidence"]["route"] for sample in samples),
            "context": any(sample["evidence"]["context"] for sample in samples),
            "capability": any(sample["evidence"]["capability"] for sample in samples),
            "loop": any(sample["evidence"]["loop"] for sample in samples),
            "worker": any(sample["evidence"]["worker"] for sample in samples),
            "provider_matrix": bool(matrix_summaries),
        }
        required_coverage = ["route", "context", "capability", "loop", "worker"]
        missing = [key for key in required_coverage if not coverage[key]]
        sample_count = len(samples)
        if sample_count < 3:
            status = "needs_more_samples"
        elif missing:
            status = "needs_evidence"
        elif sample_count <= 5:
            status = "ready"
        else:
            status = "oversampled"
        next_actions = []
        if sample_count < 3:
            next_actions.append(
                f"Collect {3 - sample_count} more scoped real-provider validation sample(s)."
            )
        if missing:
            next_actions.append("Collect missing evidence categories: " + ", ".join(missing) + ".")
        if sample_count > 5:
            next_actions.append("Keep the v0.2 rolling validation bundle focused to 3-5 samples.")
        if not next_actions:
            next_actions.append(
                "Review this bundle with gate-status and capability-report before widening dogfooding."
            )
        return {
            "schema_version": "0.1.0",
            "created_at": now_iso(),
            "purpose": "v0.2.0-alpha rolling real-provider scoped task validation",
            "status": status,
            "sample_count": sample_count,
            "matrix_summary_count": len(matrix_summaries),
            "required_sample_range": {"min": 3, "max": 5},
            "coverage": coverage,
            "missing_evidence_categories": missing,
            "samples": samples,
            "matrix_summaries": matrix_summaries,
            "next_actions": next_actions,
        }

    def _rolling_matrix_summaries(self) -> list[dict[str, Any]]:
        matrix_dir = self.agent_dir / "verification" / "real_provider_matrix"
        if not matrix_dir.exists():
            return []
        paths = sorted(
            (
                path
                for path in matrix_dir.glob("**/matrix_summary.json")
                if path.is_file() and not _is_protected(path)
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[: self.max_runs]
        summaries: list[dict[str, Any]] = []
        for path in paths:
            summary = self._read_json(path)
            if not summary:
                continue
            cases = summary.get("cases")
            compact_cases = [
                self._rolling_matrix_case_sample(case)
                for case in cases
                if isinstance(case, dict)
            ] if isinstance(cases, list) else []
            summaries.append(
                {
                    "path": _rel(self.root, path),
                    "matrix": str(summary.get("matrix") or ""),
                    "matrix_preset": summary.get("matrix_preset"),
                    "provider_mode": str(summary.get("provider_mode") or "real"),
                    "ok": bool(summary.get("ok")),
                    "case_count": int(summary.get("case_count") or 0),
                    "passed": int(summary.get("passed") or 0),
                    "failed": int(summary.get("failed") or 0),
                    "duration_seconds": summary.get("duration_seconds"),
                    "cases": compact_cases,
                }
            )
        return summaries

    def _rolling_matrix_case_sample(self, case: dict[str, Any]) -> dict[str, Any]:
        context_strategy = case.get("context_strategy")
        context_strategy = context_strategy if isinstance(context_strategy, dict) else {}
        agent_loop = case.get("agent_loop")
        agent_loop = agent_loop if isinstance(agent_loop, dict) else {}
        return {
            "name": str(case.get("name") or ""),
            "task_kind": str(case.get("task_kind") or ""),
            "route": str(case.get("route") or ""),
            "ok": bool(case.get("ok")),
            "model_call_count": context_strategy.get("model_call_count"),
            "strong_model_calls": context_strategy.get("strong_model_calls"),
            "task_execution_model_calls": context_strategy.get("task_execution_model_calls"),
            "task_repair_model_calls": context_strategy.get("task_repair_model_calls"),
            "run_review_model_calls": context_strategy.get("run_review_model_calls"),
            "slim_model_calls": context_strategy.get("slim_model_calls"),
            "fast_path_task_kinds": context_strategy.get("fast_path_task_kinds") or {},
            "budget_repair_attempts": agent_loop.get("budget_repair_attempts"),
            "final_report": case.get("final_report"),
        }

    def _rolling_validation_sample(self, run_dir: Path) -> dict[str, Any]:
        run = self._read_json(run_dir / "run.json")
        model_calls = self._read_jsonl(run_dir / "model_calls.jsonl")
        context_snapshots = self._read_jsonl(run_dir / "context_budget_snapshots.jsonl")
        capability_decisions = self._read_jsonl(run_dir / "capability_decisions.jsonl")
        loop_decisions = self._read_jsonl(run_dir / "agent_loop_decisions.jsonl")
        loop_executions = self._read_jsonl(run_dir / "agent_loop_execution_results.jsonl")
        loop_observations = self._read_jsonl(run_dir / "agent_loop_observations.jsonl")
        workers = self._read_jsonl(run_dir / "workers.jsonl")
        worker_results = self._read_jsonl(run_dir / "worker_results.jsonl")
        task_execution = self._read_jsonl(run_dir / "task_execution_evidence.jsonl")
        loop_summary = self._read_json(run_dir / "agent_loop_run_summary.json")
        agent_run_graph = self._read_json(run_dir / "agent_run_graph.json")
        evidence = {
            "route": bool(model_calls),
            "context": bool(context_snapshots),
            "capability": bool(capability_decisions),
            "loop": bool(loop_summary or loop_decisions or loop_executions or loop_observations),
            "worker": bool(workers or worker_results or agent_run_graph),
        }
        evidence["has_any_runtime_evidence"] = any(evidence.values()) or bool(task_execution)
        model_routes = self._model_routes(model_calls)
        return {
            "run_id": run_dir.name,
            "status": str(run.get("status") or "unknown"),
            "summary": str(run.get("summary") or run.get("goal") or ""),
            "current_phase": str(run.get("current_phase") or ""),
            "model_routes": model_routes,
            "loop_exit_reason": str(loop_summary.get("exit_reason") or ""),
            "loop_recommended_command": loop_summary.get("recommended_command"),
            "worker_statuses": self._status_counts(worker_results),
            "task_execution_statuses": self._status_counts(task_execution),
            "context_pressure": self._context_pressure(context_snapshots),
            "capability_decision_count": len(capability_decisions),
            "agent_run_graph_status": str(agent_run_graph.get("status") or ""),
            "collaboration_summary": agent_run_graph.get("collaboration_summary") or {},
            "evidence": evidence,
            "evidence_refs": self._rolling_validation_refs(run_dir),
        }

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists() or _is_protected(path):
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists() or _is_protected(path):
            return []
        items: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                items.append(data)
        return items

    def _model_routes(self, model_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        routes: dict[str, dict[str, Any]] = {}
        for call in model_calls:
            key = "/".join(
                [
                    str(call.get("model_provider") or "unknown"),
                    str(call.get("model_name") or "unknown"),
                    str(call.get("purpose") or "unknown"),
                    str(call.get("model_tier") or "unknown"),
                ]
            )
            route = routes.setdefault(
                key,
                {
                    "route": key,
                    "total": 0,
                    "success": 0,
                    "failure": 0,
                    "deadline_ms_values": [],
                    "duration_ms_values": [],
                },
            )
            route["total"] += 1
            status = str(call.get("status") or "")
            if status == "success":
                route["success"] += 1
            elif status == "failure":
                route["failure"] += 1
            for source_key, target_key in (
                ("deadline_ms", "deadline_ms_values"),
                ("duration_ms", "duration_ms_values"),
            ):
                value = call.get(source_key)
                if isinstance(value, int | float):
                    route[target_key].append(int(value))
        return [
            {
                "route": item["route"],
                "total": item["total"],
                "success": item["success"],
                "failure": item["failure"],
                "deadline_ms_p95": _percentile(item["deadline_ms_values"], 0.95),
                "duration_ms_p95": _percentile(item["duration_ms_values"], 0.95),
            }
            for item in routes.values()
        ]

    def _status_counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _context_pressure(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        ratios = [
            float(item.get("context_window_ratio") or 0.0)
            for item in snapshots
            if isinstance(item.get("context_window_ratio"), int | float)
        ]
        boundary_statuses = []
        for item in snapshots:
            boundary = item.get("compact_boundary")
            if isinstance(boundary, dict) and boundary.get("status"):
                boundary_statuses.append(str(boundary.get("status")))
        return {
            "snapshot_count": len(snapshots),
            "max_context_window_ratio": max(ratios) if ratios else 0.0,
            "compact_boundary_statuses": sorted(set(boundary_statuses)),
        }

    def _rolling_validation_refs(self, run_dir: Path) -> list[str]:
        refs = []
        for name in [
            "run.json",
            "model_calls.jsonl",
            "context_budget_snapshots.jsonl",
            "capability_decisions.jsonl",
            "agent_loop_run_summary.json",
            "agent_loop_decisions.jsonl",
            "agent_loop_execution_results.jsonl",
            "agent_loop_observations.jsonl",
            "workers.jsonl",
            "worker_results.jsonl",
            "agent_run_graph.json",
        ]:
            path = run_dir / name
            if path.exists() and not _is_protected(path):
                refs.append(_rel(self.root, path))
        return refs

    def _stage_file(self, path: Path, staging: dict[str, str], warnings: list[str]) -> None:
        if not path.exists() or _is_protected(path):
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warnings.append(f"Skipped non-JSON file: {_rel(self.root, path)}")
            return
        except OSError as exc:
            warnings.append(f"Skipped unreadable file {_rel(self.root, path)}: {exc}")
            return
        staging[_rel(self.root, path)] = _json_text(_redact(data))

    def _stage_jsonl_tail(
        self,
        path: Path,
        staging: dict[str, str],
        warnings: list[str],
        *,
        limit: int,
    ) -> None:
        if not path.exists() or _is_protected(path):
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError as exc:
            warnings.append(f"Skipped unreadable file {_rel(self.root, path)}: {exc}")
            return
        redacted_lines: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                redacted_lines.append(json.dumps(_redact(json.loads(line)), ensure_ascii=False))
            except json.JSONDecodeError:
                redacted_lines.append(_redact_text(line))
        staging[_rel(self.root, path)] = "\n".join(redacted_lines) + (
            "\n" if redacted_lines else ""
        )

    def _all_model_calls(self) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        runs_dir = self.agent_dir / "runs"
        if not runs_dir.exists():
            return calls
        for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True)[
            : self.max_runs
        ]:
            path = run_dir / "model_calls.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    calls.append(item)
        return calls


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + "=[REDACTED]", redacted)
    return redacted


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(secret in normalized for secret in SECRET_KEYS)


def _is_protected(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return any(item in parts for item in PROTECTED_PARTS) or path.suffix.lower() in {
        ".key",
        ".pem",
    }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _json_text(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _run_dir_sort_key(path: Path) -> tuple[float, str]:
    candidates = [
        path / "run.json",
        path / "agent_loop_run_summary.json",
        path / "cost_report.json",
    ]
    mtimes = []
    for candidate in candidates:
        try:
            if candidate.exists():
                mtimes.append(candidate.stat().st_mtime)
        except OSError:
            continue
    try:
        mtimes.append(path.stat().st_mtime)
    except OSError:
        pass
    return (max(mtimes) if mtimes else 0.0, path.name)


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]
