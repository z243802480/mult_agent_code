from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.runtime_context import RuntimeContext
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
    # Pre-flight declared-scope disjointness (ADR-0023 B1-b): before any candidate is promoted,
    # reject a batch whose tasks DECLARE overlapping write_scope — two writers claiming the same
    # path can never be safely merged in parallel, so they must not run as an isolated-write batch.
    # This is the cheap declared-intent gate; `_cross_task_file_conflicts` is the post-execution
    # backstop over what the candidates ACTUALLY wrote. A single task can never self-conflict, so
    # single-task callers (preview_promotion) stay ok. Readonly experts declare no write_scope →
    # empty owners → ok, so readonly fanout is unaffected.
    owners: dict[str, list[str]] = {}
    for task in tasks:
        task_id = str(task.get("task_id") or "unknown")
        for raw in task.get("write_scope") or []:
            path = str(raw).replace("\\", "/").strip().lstrip("/")
            if not path:
                continue
            bucket = owners.setdefault(path, [])
            if task_id not in bucket:
                bucket.append(task_id)
    conflicts = {path: ids for path, ids in owners.items() if len(ids) > 1}
    blocked = sorted({task_id for ids in conflicts.values() for task_id in ids})
    violations = [
        f"{path}: declared in write_scope of multiple tasks ({', '.join(ids)})"
        for path, ids in sorted(conflicts.items())
    ]
    all_task_ids = [str(task.get("task_id") or "unknown") for task in tasks]
    return {
        "ok": not conflicts,
        "allowed_task_ids": [task_id for task_id in all_task_ids if task_id not in blocked],
        "blocked_task_ids": blocked,
        "violations": violations,
        "skipped": False,
        "reason": (
            "Declared write scopes are disjoint."
            if not conflicts
            else "Declared write scopes overlap; disjoint-write fanout blocked before promotion."
        ),
    }


def _cross_task_file_conflicts(task_results: list[dict[str, Any]]) -> list[str]:
    owners: dict[str, list[str]] = {}
    for item in task_results:
        raw_merge_gate = item.get("merge_gate")
        merge_gate = raw_merge_gate if isinstance(raw_merge_gate, dict) else {}
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
