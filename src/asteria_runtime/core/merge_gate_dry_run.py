from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.disjoint_write_gate import DisjointWriteGate
from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import parallel_safety
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class MergeGateDryRunResult:
    ok: bool
    task_results: list[dict[str, Any]]
    disjoint_write_gate: dict[str, Any]
    batch_violations: list[str]
    summary: str

    def to_record(
        self,
        *,
        merge_gate_dry_run_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "merge_gate_dry_run_id": merge_gate_dry_run_id,
            "run_id": run_id,
            "dry_run": True,
            "ok": self.ok,
            "task_results": self.task_results,
            "disjoint_write_gate": self.disjoint_write_gate,
            "batch_violations": self.batch_violations,
            "summary": self.summary,
            "created_at": now_iso(),
        }


@dataclass(frozen=True)
class MergeGateDryRunner:
    validator: SchemaValidator
    actor: str = "MergeGateDryRunner"

    def evaluate_single(
        self,
        task: dict,
        export: dict,
        verification_results: list[Any],
    ) -> dict[str, Any]:
        merge_gate = MergeGate().evaluate(
            task,
            list(export.get("changed_files") or []),
            verification_results,
        )
        return {
            "task_id": str(task.get("task_id") or export.get("task_id") or "unknown"),
            "candidate_export_id": str(export.get("candidate_export_id") or ""),
            "candidate_id": str(export.get("candidate_id") or ""),
            "merge_gate": merge_gate.to_dict(),
            "export_status": str(export.get("export_status") or ""),
        }

    def evaluate_batch(
        self,
        tasks: list[dict],
        exports: list[dict],
        verification_by_task: dict[str, list[Any]] | None = None,
    ) -> MergeGateDryRunResult:
        verification_by_task = verification_by_task or {}
        export_by_task = {
            str(item.get("task_id") or ""): item for item in exports if item.get("task_id")
        }
        disjoint = _disjoint_write_gate_result(tasks)
        task_results = []
        for task in tasks:
            task_id = str(task.get("task_id") or "unknown")
            export = export_by_task.get(task_id) or {
                "task_id": task_id,
                "changed_files": [],
                "export_status": "empty",
            }
            task_results.append(
                self.evaluate_single(task, export, verification_by_task.get(task_id, []))
            )
        batch_violations = _cross_task_file_conflicts(task_results)
        per_task_ok = all(
            isinstance(item.get("merge_gate"), dict) and item["merge_gate"].get("ok") is True
            for item in task_results
        )
        ok = bool(disjoint.get("ok")) and per_task_ok and not batch_violations
        summary = (
            "Merge gate dry-run passed."
            if ok
            else "Merge gate dry-run blocked: "
            + "; ".join(
                batch_violations
                + [
                    violation
                    for item in task_results
                    for violation in (item.get("merge_gate") or {}).get("violations") or []
                ]
                + list(disjoint.get("violations") or [])
            )
        )
        return MergeGateDryRunResult(
            ok=ok,
            task_results=task_results,
            disjoint_write_gate=disjoint,
            batch_violations=batch_violations,
            summary=summary,
        )

    def persist(self, context: RuntimeContext, result: MergeGateDryRunResult) -> dict[str, Any]:
        if context.run_dir is None:
            return result.to_record(
                merge_gate_dry_run_id="merge-gate-dry-run-0001",
                run_id=context.run_id or "",
            )
        path = context.run_dir / "merge_gate_dry_runs.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "merge_gate_dry_run") if path.exists() else []
        record = result.to_record(
            merge_gate_dry_run_id=f"merge-gate-dry-run-{len(existing) + 1:04d}",
            run_id=context.run_id or "",
        )
        store.append(path, record, "merge_gate_dry_run")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "merge_gate_dry_run",
                self.actor,
                record["summary"],
                {
                    "merge_gate_dry_run_id": record["merge_gate_dry_run_id"],
                    "ok": record["ok"],
                    "batch_violations": record["batch_violations"],
                },
            )
        return record

    def evaluate_and_persist(
        self,
        context: RuntimeContext,
        tasks: list[dict],
        exports: list[dict],
        verification_by_task: dict[str, list[Any]] | None = None,
    ) -> dict[str, Any]:
        result = self.evaluate_batch(tasks, exports, verification_by_task)
        return self.persist(context, result)


def _disjoint_write_gate_result(tasks: list[dict]) -> dict[str, Any]:
    if len(tasks) <= 1 and not any(parallel_safety(task) == "disjoint_writes" for task in tasks):
        task_id = str(tasks[0].get("task_id") or "unknown") if tasks else "unknown"
        return {
            "ok": True,
            "allowed_task_ids": [task_id] if tasks else [],
            "blocked_task_ids": [],
            "violations": [],
            "skipped": True,
            "reason": "Single serial worker; disjoint write gate not required.",
        }
    return DisjointWriteGate().evaluate(tasks).to_dict()


def _cross_task_file_conflicts(task_results: list[dict[str, Any]]) -> list[str]:
    owners: dict[str, list[str]] = {}
    for item in task_results:
        merge_gate = item.get("merge_gate") if isinstance(item.get("merge_gate"), dict) else {}
        if merge_gate.get("ok") is not True:
            continue
        task_id = str(item.get("task_id") or "unknown")
        for file_path in merge_gate.get("promotable_files") or []:
            owners.setdefault(str(file_path), []).append(task_id)
    return [
        f"{file_path}: claimed by multiple tasks ({', '.join(task_ids)})"
        for file_path, task_ids in sorted(owners.items())
        if len(task_ids) > 1
    ]
