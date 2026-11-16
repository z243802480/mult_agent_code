"""Bounded, current artifact evidence for semantic review, independent of file format."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from uuid import uuid4

from asteria_runtime.core.content_preservation import PROTECTED
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.utils.time import now_iso

MAX_FILES = 16
MAX_FILE_BYTES = 65_536
MAX_TOTAL_CONTENT_BYTES = 196_608


def collect_review_artifacts(context: RuntimeContext, goal: dict, board: dict) -> dict:
    paths = [p for p in goal.get("target_outputs", []) if isinstance(p, str) and p]
    for task in board.get("tasks", []):
        if not isinstance(task, dict) or task.get("status") == "discarded":
            continue
        for key in ("expected_artifacts", "expected_changed_files"):
            paths.extend(p for p in task.get(key, []) if isinstance(p, str) and p)
    paths = list(dict.fromkeys(paths))
    safe_context = replace(context, policy={
        **context.policy, "protected_paths": [*PROTECTED, *context.policy.get("protected_paths", [])],
    })
    files: list[dict] = []
    remaining = MAX_TOTAL_CONTENT_BYTES
    for path in paths:
        if len(files) >= MAX_FILES or remaining <= 0:
            break
        row: dict = {"path": path, "status": "unavailable", "content": None,
               "content_sha256": None, "metadata": {}}
        try:
            # The byte cap is the bound; do not silently retain read_file's default
            # 800-line page for a file that fits (the real review fixture has 830 lines).
            result = ReadFileTool(max_bytes=min(MAX_FILE_BYTES, remaining)).run(
                safe_context, path, limit=MAX_FILE_BYTES,
            )
            if result.ok:
                data = dict(result.data)
                content = data.pop("content")
                encoded = content.encode("utf8")
                remaining -= len(encoded)
                if "has_more" in data:
                    complete = data["has_more"] is False and not data.get("byte_truncated")
                else:
                    total = data.get("total_lines")
                    complete = total is not None and data.get("line_start", 1) == 1 and data.get("line_end", total) == total
                row.update(status="complete" if complete else "partial", content=content,
                           content_sha256=hashlib.sha256(encoded).hexdigest(), metadata=data)
            else:
                row["metadata"] = {"error": result.error or "read_unavailable"}
        except (OSError, UnicodeError, PermissionError) as exc:
            row["metadata"] = {"error": type(exc).__name__}
        files.append(row)
    omitted = paths[len(files):]
    evidence = {
        "schema_version": "0.1.0", "evidence_id": "review-artifacts-" + uuid4().hex,
        "run_id": context.run_id, "workspace_root": str(context.root.resolve()), "captured_at": now_iso(),
        "source": "current_workspace", "files": files,
        "omitted_paths": omitted,
        "complete": not omitted and all(row["status"] == "complete" for row in files),
    }
    context.validator.validate("review_artifacts", evidence)
    return evidence
