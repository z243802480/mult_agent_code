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

        manifest = self._manifest(warnings)
        staging["manifest.json"] = _json_text(manifest)
        self._add_summary_files(staging, warnings)
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
        )

    def _manifest(self, warnings: list[str]) -> dict[str, Any]:
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
                "success_rate": round(item["success"] / item["total"], 4)
                if item["total"]
                else 0.0,
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
            "warnings": warnings,
        }

    def _add_summary_files(self, staging: dict[str, str], warnings: list[str]) -> None:
        candidates = [
            self.agent_dir / "model" / "real_model_gate_report.json",
            self.agent_dir / "model" / "real_model_smoke_summary.json",
            self.agent_dir / "model" / "capability_profile.json",
            self.agent_dir / "verification" / "real_model_acceptance_gray.json",
            self.agent_dir / "verification" / "real_model_acceptance_core.json",
            self.agent_dir / "verification" / "acceptance_report_core.json",
            self.agent_dir / "verification" / "acceptance_gate_core.json",
        ]
        for path in candidates:
            self._stage_file(path, staging, warnings)

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
            self._stage_jsonl_tail(
                run_dir / "task_execution_evidence.jsonl", staging, warnings, limit=250
            )
            self._stage_jsonl_tail(run_dir / "worker_results.jsonl", staging, warnings, limit=250)
            self._stage_jsonl_tail(
                run_dir / "validation_results.jsonl", staging, warnings, limit=250
            )

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
        staging[_rel(self.root, path)] = "\n".join(redacted_lines) + ("\n" if redacted_lines else "")

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


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]
