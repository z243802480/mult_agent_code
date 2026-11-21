"""Source-linked change and criterion views; no semantic verdict or domain rules."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from asteria_runtime.core.content_preservation import PROTECTED
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.security.path_guard import PathGuard

MAX_BACKUPS = 64
MAX_MANIFEST_BYTES = 65_536
MAX_BASELINE_BYTES = 65_536
MAX_DIFF_BYTES = 32_768
MAX_CRITERIA = 64
MAX_CRITERION_CHARS = 2048
MAX_CRITERIA_CHARS = 16_384
MAX_TASKS = 16
MAX_OBSERVATIONS_PER_TASK = 32


def scoped_observations(run_id: str | None, observations: list[dict]) -> list[dict]:
    """Select uniquely attributable receipts, without selecting a winner on conflict."""
    if not run_id:
        return []
    own = [row for row in observations if row.get("run_id") == run_id]
    calls = Counter(row.get("tool_call_id") for row in own)
    identities = Counter(row.get("observation_id") for row in own)
    return [row for row in own
            if isinstance(row.get("tool_call_id"), str) and row["tool_call_id"]
            and isinstance(row.get("observation_id"), str) and row["observation_id"]
            and calls[row["tool_call_id"]] == identities[row["observation_id"]] == 1]


def _data(row: dict) -> dict:
    observation = row.get("observation")
    data = observation.get("data") if isinstance(observation, dict) else None
    return data if isinstance(data, dict) else {}


def _read_internal(path: Path, workspace: Path, limit: int) -> bytes:
    path.resolve().relative_to(workspace.resolve())
    for part in (path, *path.parents):
        if part == workspace:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise PermissionError("Linked backup path")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Backup read capacity exceeded")
    return data


def _baseline(context: RuntimeContext, path: str, writes: list[dict], cache: dict,
              identities: set[tuple[str, str]]) -> tuple[str, dict]:
    guard = PathGuard(context.root, [*PROTECTED, *context.policy.get("protected_paths", [])])
    relative = guard.resolve_for_read(path).relative_to(context.root.resolve()).as_posix()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", context.run_id or ""):
        raise ValueError("No bound run")
    for row in writes:
        backup_id = _data(row)["backup_id"]
        if not isinstance(backup_id, str) or not re.fullmatch(r"backup-[A-Za-z0-9_-]+", backup_id):
            raise ValueError("Invalid backup identity")
        folder = context.asteria_dir / "backups" / str(context.run_id) / backup_id
        manifest_path = folder / "manifest.json"
        if backup_id not in cache:
            manifest = json.loads(_read_internal(manifest_path, context.root, MAX_MANIFEST_BYTES))
            context.validator.validate("file_backup_manifest", manifest)
            if manifest["run_id"] != context.run_id or manifest["backup_id"] != backup_id:
                raise ValueError("Backup run or identity mismatch")
            cache[backup_id] = manifest
        manifest = cache[backup_id]
        item = next((f for f in manifest["files"] if f["path"] == relative), None)
        if item is None:
            continue
        if (row.get("tool_call_id"), row.get("observation_id")) not in identities:
            raise ValueError("Earliest matching backup has ambiguous observation identity")
        data = b""
        if item["existed"]:
            expected = "files/" + hashlib.sha256(relative.encode("utf8")).hexdigest()[:16] + ".bak"
            if item["backup_path"] != expected:
                raise ValueError("Unexpected backup member path")
            data = _read_internal(folder / expected, context.root, MAX_BASELINE_BYTES)
            if len(data) != item["size"]:
                raise ValueError("Backup size mismatch")
        elif item["backup_path"] is not None:
            raise ValueError("Absent source has backup content")
        return data.decode("utf8"), {
            "source": "recorded_pre_tool_backup", "backup_id": backup_id,
            "manifest_ref": manifest_path.relative_to(context.root).as_posix(),
            "task_id": row["task_id"], "tool_call_id": row["tool_call_id"],
            "observation_id": row["observation_id"], "existed": item["existed"],
            "content_sha256": hashlib.sha256(data).hexdigest(),
        }
    raise ValueError("No recorded baseline in bounded active-task write observations")


def collect_review_focus(context: RuntimeContext, artifacts: dict, goal: dict,
                         board: dict, observations: list[dict]) -> dict:
    tasks = [(i, t) for i, t in enumerate(board.get("tasks", [])) if t.get("status") != "discarded"]
    active = {t["task_id"] for _, t in tasks if "task_id" in t}
    task_counts = Counter(t.get("task_id") for t in board.get("tasks", []))
    scoped = scoped_observations(context.run_id, observations)
    identities = {(r["tool_call_id"], r["observation_id"]) for r in scoped
                  if task_counts[r.get("task_id")] == 1}
    writes = [r for r in observations if r.get("run_id") == context.run_id
              and r.get("task_id") in active and r.get("ok") is True
              and r.get("tool_name") in {"write_file", "apply_patch"}
              and isinstance(_data(r).get("backup_id"), str)]
    selected = writes[:MAX_BACKUPS]
    changes: list[dict] = []
    cache: dict[str, dict] = {}
    remaining = MAX_DIFF_BYTES
    for file in artifacts["files"]:
        row: dict = {"path": file["path"], "current_content_sha256": file["content_sha256"],
               "status": "unavailable", "baseline": None, "diff": None, "omitted_diff_bytes": 0,
               "reason": "Current content is missing or partial"}
        if file["status"] == "complete":
            try:
                before, baseline = _baseline(context, file["path"], selected, cache, identities)
                # This is a text-line view, not a byte preservation or authorization verdict.
                diff = "\n".join(difflib.unified_diff(before.splitlines(), file["content"].splitlines(),
                    fromfile="before/" + file["path"], tofile="current/" + file["path"], lineterm=""))
                encoded = diff.encode("utf8")
                shown = encoded[:remaining].decode("utf8", errors="ignore")
                used = len(shown.encode("utf8"))
                remaining -= used
                row.update(status="complete" if used == len(encoded) else "partial", baseline=baseline,
                           diff=shown, omitted_diff_bytes=len(encoded) - used, reason=None)
            except (OSError, ValueError, PermissionError, UnicodeError) as exc:
                row["reason"] = type(exc).__name__
        changes.append(row)

    criteria: list[dict] = []
    omitted_criteria = 0
    remaining_criteria = MAX_CRITERIA_CHARS
    def add(text: object, source: str, kind: str, task_id: str | None = None, *, source_partial: bool = False) -> None:
        nonlocal omitted_criteria, remaining_criteria
        if isinstance(text, str) and text.strip():
            if len(criteria) >= MAX_CRITERIA or remaining_criteria <= 0:
                omitted_criteria += 1
                return
            shown = text[:min(MAX_CRITERION_CHARS, remaining_criteria)]
            remaining_criteria -= len(shown)
            criteria.append({"text": shown, "source_ref": source,
                             "source_kind": kind, "task_id": task_id,
                             "truncated": len(shown) < len(text) or source_partial})
    add(goal.get("original_goal"), "goal_spec.original_goal", "user_request")
    guidance = (artifacts.get("review_basis") or {}).get("project_guidance") or {}
    add(guidance.get("content"), "review_basis.project_guidance.content", "current_project_guidance",
        source_partial=guidance.get("status") == "partial")
    for i, requirement in enumerate(goal.get("expanded_requirements", [])):
        add(requirement.get("description"), f"goal_spec.expanded_requirements[{i}].description", "model_proposal")
        for j, text in enumerate(requirement.get("acceptance", [])):
            add(text, f"goal_spec.expanded_requirements[{i}].acceptance[{j}]", "model_proposal")
    for i, text in enumerate(goal.get("definition_of_done", [])):
        add(text, f"goal_spec.definition_of_done[{i}]", "model_proposal")
    task_evidence = []
    for i, task in tasks:
        for j, text in enumerate(task.get("acceptance", [])):
            add(text, f"task_plan.tasks[{i}].acceptance[{j}]", "task_contract", task.get("task_id"))
    for _, task in tasks[:MAX_TASKS]:
        if not isinstance(task.get("task_id"), str) or task_counts[task["task_id"]] != 1:
            continue
        related = [r["observation_id"] for r in scoped
                   if r.get("task_id") == task.get("task_id") and r.get("observation_id")]
        task_evidence.append({"task_id": task.get("task_id"),
                              "observation_ids": related[-MAX_OBSERVATIONS_PER_TASK:],
                              "omitted_observations": max(0, len(related) - MAX_OBSERVATIONS_PER_TASK),
                              "relation": "same_task_only_not_criterion_coverage"})
    return {
        "changes": changes, "criteria": criteria, "task_evidence": task_evidence,
        "omitted_criteria": omitted_criteria, "omitted_tasks": len(tasks) - len(task_evidence),
        "omitted_write_observations": max(0, len(writes) - MAX_BACKUPS),
        "semantic_coverage": "unassessed", "original_request_ref": "review_basis.original_request",
        "baseline_scope": "Earliest available recorded pre-tool backup for active tasks, not necessarily goal start. "
                          "Text-line diff excludes line-ending comparisons; missing baseline is unknown, not unchanged.",
    }
