"""Carry real, unchanged disk modifications across a same-task user pause.

Uses the existing stat snapshot (mtime_ns, size), not file contents. This is conservative
completion evidence, not a content-integrity or sandbox guarantee. Validation is never reused.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.workspace_snapshot import MAX_SCAN_FILES, Snapshot, changed_paths
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError


def _path(context: RuntimeContext, task: dict) -> Path | None:
    if context.run_dir is None or not context.run_id:
        return None
    key = hashlib.sha256(str(task["task_id"]).encode()).hexdigest()
    return context.run_dir / "task_pause_checkpoints" / f"{key}.json"


def _contract_hash(task: dict) -> str:
    keys = (
        "title",
        "description",
        "task_kind",
        "acceptance",
        "expected_artifacts",
        "expected_changed_files",
        "write_scope",
        "edit_boundary",
        "completion_contract",
        "validation_commands",
        "verification_policy",
    )
    content = json.dumps(
        {key: task.get(key) for key in keys},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()


def previous_pause_changes(
    context: RuntimeContext,
    task: dict,
    current: Snapshot | None,
) -> list[str]:
    path = _path(context, task)
    if path is None or current is None:
        return []
    try:
        saved = JsonStore(context.validator).read(path, "task_pause_checkpoint")
    except (OSError, ValueError, SchemaValidationError):
        return []  # A missing/invalid checkpoint is never evidence of progress.
    if (
        saved["run_id"] != context.run_id
        or saved["task_id"] != task["task_id"]
        or saved["task_contract_hash"] != _contract_hash(task)
    ):
        return []
    return sorted(
        name
        for name, signature in saved["changes"].items()
        if (signature is None and name not in current)
        or (signature is not None and name in current and tuple(signature) == current[name])
    )


def record_pause_changes(
    context: RuntimeContext,
    task: dict,
    before: Snapshot | None,
    after: Snapshot | None,
) -> None:
    path = _path(context, task)
    if path is None:
        return
    names = set(changed_paths(before, after))
    names.update(previous_pause_changes(context, task, before))
    # An unavailable scan replaces an older checkpoint with no evidence, never stale green.
    available = before is not None and after is not None and len(names) <= MAX_SCAN_FILES
    changes = (
        {name: list(after[name]) if name in after else None for name in names}
        if available and after is not None
        else {}
    )
    data = {
        "schema_version": "0.1.0",
        "run_id": context.run_id,
        "task_id": task["task_id"],
        "task_contract_hash": _contract_hash(task),
        "changes": changes,
    }
    JsonStore(context.validator).write(path, data, "task_pause_checkpoint")
    if context.event_logger:
        context.event_logger.record(
            context.run_id,
            "task_pause_checkpoint_recorded",
            "ExecuteCommand",
            "Recorded same-task pause checkpoint.",
            {
                "task_id": task["task_id"],
                "checkpoint_path": str(path),
                "changed_file_count": len(changes),
                "snapshot_available": available,
            },
        )


def clear_pause_changes(context: RuntimeContext, task: dict) -> None:
    path = _path(context, task)
    if path is not None:
        path.unlink(missing_ok=True)
