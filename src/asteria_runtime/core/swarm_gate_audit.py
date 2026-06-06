from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class SwarmGateCheck:
    name: str
    ok: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "reason": self.reason}


@dataclass(frozen=True)
class SwarmGateAuditResult:
    ok: bool
    checks: list[SwarmGateCheck] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "checks": [item.to_dict() for item in self.checks],
        }


class SwarmGateAuditor:
    """Audit Phase 5 swarm evidence chain in a run directory (maintainer gray path)."""

    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator
        self._store = JsonlStore(validator)

    def evaluate_run_dir(self, run_dir: Path) -> SwarmGateAuditResult:
        checks: list[SwarmGateCheck] = []
        workers = self._read(run_dir, "workers.jsonl", "worker_invocation")
        worker_results = self._read(run_dir, "worker_results.jsonl", "worker_result")
        exports = self._read(run_dir, "candidate_exports.jsonl", "candidate_export")
        dry_runs = self._read(run_dir, "merge_gate_dry_runs.jsonl", "merge_gate_dry_run")
        promotions = self._read(run_dir, "candidate_promotions.jsonl", "candidate_promotion")

        checks.append(self._check_workers_present(workers, worker_results))
        checks.append(self._check_harness_write_workers(workers))
        checks.append(self._check_candidate_exports(exports))
        checks.append(self._check_merge_dry_run(dry_runs))
        checks.append(self._check_disjoint_batch(dry_runs, exports))
        if promotions:
            checks.append(self._check_promotions_optional(promotions))

        ok = all(item.ok for item in checks)
        summary = (
            "Phase 5 swarm gray path evidence chain passed."
            if ok
            else "Swarm gate audit blocked: "
            + "; ".join(item.reason for item in checks if not item.ok)
        )
        return SwarmGateAuditResult(ok=ok, checks=checks, summary=summary)

    def _read(self, run_dir: Path, name: str, schema: str) -> list[dict]:
        path = run_dir / name
        if not path.exists():
            return []
        return self._store.read_all(path, schema)

    def _check_workers_present(
        self,
        workers: list[dict],
        worker_results: list[dict],
    ) -> SwarmGateCheck:
        if len(workers) < 1:
            return SwarmGateCheck("workers_recorded", False, "workers.jsonl is empty or missing.")
        if len(worker_results) < 1:
            return SwarmGateCheck("worker_results_recorded", False, "worker_results.jsonl is empty or missing.")
        return SwarmGateCheck(
            "workers_recorded",
            True,
            f"{len(workers)} worker invocation(s) and {len(worker_results)} result(s) recorded.",
        )

    def _check_harness_write_workers(self, workers: list[dict]) -> SwarmGateCheck:
        harness = [
            item
            for item in workers
            if str(item.get("execution_profile_id") or "") == "harness"
            or str(item.get("spawn_kind") or "") == "harness_write"
        ]
        if not harness:
            return SwarmGateCheck(
                "harness_write_workers",
                False,
                "No harness write workers with execution_profile_id or spawn_kind.",
            )
        return SwarmGateCheck(
            "harness_write_workers",
            True,
            f"{len(harness)} harness write worker(s) recorded.",
        )

    def _check_candidate_exports(self, exports: list[dict]) -> SwarmGateCheck:
        if not exports:
            return SwarmGateCheck("candidate_exports", False, "candidate_exports.jsonl is missing or empty.")
        ready = [item for item in exports if str(item.get("export_status") or "") == "ready"]
        if not ready:
            return SwarmGateCheck("candidate_exports", False, "No ready candidate exports.")
        return SwarmGateCheck(
            "candidate_exports",
            True,
            f"{len(ready)} ready candidate export(s).",
        )

    def _check_merge_dry_run(self, dry_runs: list[dict]) -> SwarmGateCheck:
        if not dry_runs:
            return SwarmGateCheck("merge_dry_run", False, "merge_gate_dry_runs.jsonl is missing or empty.")
        latest = dry_runs[-1]
        if latest.get("dry_run") is not True:
            return SwarmGateCheck("merge_dry_run", False, "Latest merge dry-run record is not marked dry_run.")
        if latest.get("ok") is not True:
            return SwarmGateCheck(
                "merge_dry_run",
                False,
                str(latest.get("summary") or "Latest merge dry-run did not pass."),
            )
        return SwarmGateCheck("merge_dry_run", True, "Latest merge dry-run passed.")

    def _check_disjoint_batch(self, dry_runs: list[dict], exports: list[dict]) -> SwarmGateCheck:
        if len(exports) < 2:
            return SwarmGateCheck(
                "disjoint_write_batch",
                False,
                "Gray path requires at least 2 disjoint candidate exports.",
            )
        latest = dry_runs[-1] if dry_runs else {}
        disjoint = latest.get("disjoint_write_gate") if isinstance(latest.get("disjoint_write_gate"), dict) else {}
        if disjoint.get("ok") is not True:
            return SwarmGateCheck(
                "disjoint_write_batch",
                False,
                "Disjoint write gate did not pass in dry-run.",
            )
        scopes = {path for item in exports for path in item.get("changed_files") or []}
        if len(scopes) < 2:
            return SwarmGateCheck(
                "disjoint_write_batch",
                False,
                "Disjoint exports must cover at least 2 files.",
            )
        return SwarmGateCheck(
            "disjoint_write_batch",
            True,
            f"Disjoint batch covered {len(scopes)} file(s).",
        )

    def _check_promotions_optional(self, promotions: list[dict]) -> SwarmGateCheck:
        unresolved = [
            item
            for item in promotions
            if str(item.get("status") or "")
            in {"queued", "pending_manual_approval", "auto_approved", "blocked", "promotion_failed"}
        ]
        if unresolved:
            return SwarmGateCheck(
                "promotion_queue",
                True,
                f"{len(unresolved)} promotion(s) queued for maintainer review (expected in gray path).",
            )
        return SwarmGateCheck("promotion_queue", True, "Promotion queue recorded.")
