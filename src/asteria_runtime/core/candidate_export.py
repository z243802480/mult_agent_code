from __future__ import annotations

import filecmp
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.candidate_workspace import EXCLUDED_NAMES, CandidateWorkspace
from asteria_runtime.core.execution_profile import resolve_worker_execution_profile
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import write_scope
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class CandidateExporter:
    validator: SchemaValidator
    actor: str = "CandidateExporter"

    def discover_changed_files(
        self,
        candidate: CandidateWorkspace,
        *,
        task: dict | None = None,
        explicit: list[str] | None = None,
    ) -> list[str]:
        if explicit:
            return sorted({_normalize_path(path) for path in explicit if path})
        scope = write_scope(task or {})
        discovered: list[str] = []
        candidate_root = candidate.root.resolve()
        if not candidate_root.exists():
            return []
        for path in candidate_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_NAMES for part in path.parts):
                continue
            relative = _normalize_path(str(path.relative_to(candidate_root)))
            if scope and not _path_in_scope(relative, scope):
                continue
            source = (candidate.source_root / relative).resolve()
            if not source.exists() or not filecmp.cmp(source, path, shallow=False):
                discovered.append(relative)
        return sorted(set(discovered))

    def build_export(
        self,
        *,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        task: dict,
        changed_files: list[str] | None = None,
        worker_invocation_id: str | None = None,
        sequence: int = 1,
    ) -> dict:
        files = changed_files if changed_files is not None else self.discover_changed_files(
            candidate, task=task
        )
        profile = resolve_worker_execution_profile(task)
        hints = task.get("runtime_profile_hints")
        hints = hints if isinstance(hints, dict) else {}
        export_status = "ready" if files else "empty"
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_export_id": f"candidate-export-{max(1, sequence):04d}",
            "run_id": context.run_id or "",
            "task_id": str(task.get("task_id") or "unknown"),
            "candidate_id": candidate.candidate_id,
            "workspace": str(candidate.root),
            "worker_invocation_id": worker_invocation_id
            or str(hints.get("worker_invocation_id") or ""),
            "changed_files": sorted(set(files)),
            "write_scope": write_scope(task),
            "execution_profile_id": profile.profile_id,
            "export_status": export_status,
            "spawn_kind": str(hints.get("spawn_kind") or ""),
            "created_at": now_iso(),
        }

    def persist(self, context: RuntimeContext, export: dict) -> dict:
        if context.run_dir is None:
            return export
        path = context.run_dir / "candidate_exports.jsonl"
        store = JsonlStore(self.validator)
        store.append(path, export, "candidate_export")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "candidate_exported",
                self.actor,
                f"Exported {len(export.get('changed_files') or [])} file(s) for {export['task_id']}.",
                {
                    "candidate_export_id": export["candidate_export_id"],
                    "task_id": export["task_id"],
                    "candidate_id": export["candidate_id"],
                    "export_status": export["export_status"],
                },
            )
        return export

    def export_and_persist(
        self,
        *,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        task: dict,
        changed_files: list[str] | None = None,
        worker_invocation_id: str | None = None,
    ) -> dict:
        if context.run_dir is not None:
            path = context.run_dir / "candidate_exports.jsonl"
            existing = (
                JsonlStore(self.validator).read_all(path, "candidate_export")
                if path.exists()
                else []
            )
            sequence = len(existing) + 1
        else:
            sequence = 1
        export = self.build_export(
            context=context,
            candidate=candidate,
            task=task,
            changed_files=changed_files,
            worker_invocation_id=worker_invocation_id,
            sequence=sequence,
        )
        return self.persist(context, export)


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/")


def _path_in_scope(path: str, scope: list[str]) -> bool:
    normalized_path = _normalize_path(path)
    for item in scope:
        normalized_scope = _normalize_path(item)
        if not normalized_scope:
            continue
        if normalized_scope.endswith("/"):
            if normalized_path.startswith(normalized_scope):
                return True
            continue
        if normalized_path == normalized_scope or normalized_path.startswith(normalized_scope + "/"):
            return True
    return False
