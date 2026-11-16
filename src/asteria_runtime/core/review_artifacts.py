"""Bounded, current artifact evidence for semantic review, independent of file format."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from uuid import uuid4

from asteria_runtime.core.content_preservation import PROTECTED
from asteria_runtime.core.goal_provenance import proposal_origin_status
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import looks_like_file_path
from asteria_runtime.core.workspace_snapshot import observation_coverage
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.utils.time import now_iso

MAX_FILES = 16
MAX_FILE_BYTES = 65_536
MAX_TOTAL_CONTENT_BYTES = 196_608
MAX_GUIDANCE_BYTES = 16_384


def review_basis(goal: dict, *, guidance: str, guidance_present: bool) -> dict:
    """Expose provenance and observation limits, without deciding domain semantics."""
    encoded = guidance.encode("utf8") if guidance_present else b""
    content = encoded[:MAX_GUIDANCE_BYTES].decode("utf8", errors="ignore")
    return {
        "original_request": {"source": "goal_spec.original_goal", "content": goal.get("original_goal", "")},
        "goal_interpretation": {
            "origin_status": proposal_origin_status(goal),
            "producer_record": goal.get("proposal_origin"),
            "source_labels_are_model_claims": True,
            "semantics_verified_by_runtime": False,
        },
        "project_guidance": {
            "path": "AGENTS.md", "content": content,
            "status": "absent" if not guidance_present else "partial" if len(encoded) > MAX_GUIDANCE_BYTES else "complete",
            "content_sha256": hashlib.sha256(content.encode("utf8")).hexdigest(),
            "temporal_scope": "current_workspace_at_review",
        },
        "workspace_scan_coverage": observation_coverage(),
    }


def collect_review_artifacts(context: RuntimeContext, goal: dict, board: dict) -> dict:
    # Legacy GoalSpec outputs can describe outcomes, not files. Reuse the existing
    # concrete-file contract; task-declared artifact paths remain literal.
    paths = [p for p in goal.get("target_outputs", []) if isinstance(p, str) and looks_like_file_path(p)]
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
