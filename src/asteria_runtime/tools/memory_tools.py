from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.tools.base import ToolResult
from asteria_runtime.utils.time import now_iso


# Mirror of memory_entry.schema.json's type enum. The schema stays the authority — append
# validates against it — this set only exists to give the model a readable error instead of a
# raw SchemaValidationError when it invents a type.
MEMORY_ENTRY_TYPES = {
    "user_preference",
    "project_decision",
    "architecture_note",
    "research_claim",
    "experiment_lesson",
    "tool_knowledge",
    "failure_lesson",
}

# The model's own notes live in their own file, apart from the harness-written decisions.jsonl /
# failures.jsonl, so provenance is visible at the filename level and a bad run's notes can be
# deleted without touching harness evidence.
MODEL_NOTES_FILENAME = "model_notes.jsonl"

MAX_CONTENT_CHARS = 2_000
MAX_TAGS = 8
MAX_ENTRIES_PER_RUN = 20


def memory_dir(context: RuntimeContext) -> Path:
    return context.agent_dir / "memory"


def read_memory_entries_tolerant(path: Path, validator: Any) -> list[dict[str, Any]]:
    """Read memory_entry rows, skipping damaged/legacy lines instead of raising.

    ``JsonlStore.read_all`` fails the whole file on one bad row; memory files accumulate across
    schema generations (failures.jsonl predates memory_id), so recall/dedupe must degrade
    per-row like ``ContextLoader._safe_read_jsonl`` does.
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        try:
            validator.validate("memory_entry", item)
        except Exception:  # noqa: BLE001 - tolerant read: a damaged row is skipped, not fatal
            continue
        entries.append(item)
    return entries


class RememberTool:
    """The model's own write channel into durable cross-goal memory (ADR-0016: WHAT deserves
    remembering is a cognitive judgement and belongs to the model; the harness only enforces the
    boundary — schema, bounds, provenance). Harness-written memories (decisions/failures) are a
    separate, deterministic channel and stay untouched."""

    name = "remember"

    def run(
        self,
        context: RuntimeContext,
        content: str,
        type: str = "experiment_lesson",  # noqa: A002 - model-facing arg mirrors the schema field
        tags: list[str] | None = None,
        confidence: float = 0.7,
    ) -> ToolResult:
        text = str(content or "").strip()
        if not text:
            return ToolResult(
                ok=False,
                summary="remember requires non-empty content",
                error="empty_content",
            )
        if len(text) > MAX_CONTENT_CHARS:
            return ToolResult(
                ok=False,
                summary=(
                    f"remember content is {len(text)} chars; the bound is {MAX_CONTENT_CHARS}. "
                    "Distill the durable lesson instead of dumping raw output."
                ),
                error="content_too_long",
            )
        if type not in MEMORY_ENTRY_TYPES:
            return ToolResult(
                ok=False,
                summary=(
                    f"Unknown memory type: {type}. "
                    f"Valid types: {', '.join(sorted(MEMORY_ENTRY_TYPES))}"
                ),
                error="invalid_memory_type",
            )
        try:
            level = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            return ToolResult(
                ok=False,
                summary=f"confidence must be a number between 0 and 1, got: {confidence!r}",
                error="invalid_confidence",
            )
        normalized_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:MAX_TAGS]

        path = memory_dir(context) / MODEL_NOTES_FILENAME
        existing = read_memory_entries_tolerant(path, context.validator)

        # Write-time dedupe: an identical lesson re-remembered is a no-op, not a duplicate row.
        # (Read-time dedupe in ContextLoader covers cross-file dupes; this keeps the model's own
        # file from silting up when it re-learns the same thing every run.)
        for entry in existing:
            if str(entry.get("content", "")).strip() == text:
                return ToolResult(
                    ok=True,
                    summary=(
                        f"Already remembered as {entry.get('memory_id')} — no duplicate written."
                    ),
                    data={"memory_id": entry.get("memory_id"), "deduplicated": True},
                )

        if context.run_id is not None:
            run_entries = sum(
                1
                for entry in existing
                if isinstance(entry.get("source"), dict)
                and entry["source"].get("run_id") == context.run_id
            )
            if run_entries >= MAX_ENTRIES_PER_RUN:
                return ToolResult(
                    ok=False,
                    summary=(
                        f"This run already wrote {run_entries} memory entries (bound: "
                        f"{MAX_ENTRIES_PER_RUN}). Memory is for durable lessons, not a log."
                    ),
                    error="memory_write_budget_exhausted",
                )

        record = {
            "schema_version": "0.1.0",
            "memory_id": f"note-{len(existing) + 1:04d}",
            "type": type,
            "content": text,
            "source": {"kind": "model", "run_id": context.run_id},
            "tags": normalized_tags,
            "confidence": level,
            "created_at": now_iso(),
        }
        JsonlStore(context.validator).append(path, record, "memory_entry")
        return ToolResult(
            ok=True,
            summary=f"Remembered {type} {record['memory_id']}: {text[:80]}",
            data={
                "memory_id": record["memory_id"],
                "type": type,
                "path": path.relative_to(context.root).as_posix(),
                "deduplicated": False,
            },
        )


class RecallMemoryTool:
    """Fetch the full text of a memory entry listed (possibly truncated) in the
    ``memory`` index of runtime_context. memory_id is not globally unique across files
    (decisions.jsonl and failures.jsonl both number from memory-0001), so every match is
    returned with its source file."""

    name = "recall_memory"

    def run(self, context: RuntimeContext, memory_id: str) -> ToolResult:
        wanted = str(memory_id or "").strip()
        if not wanted:
            return ToolResult(
                ok=False,
                summary="recall_memory requires a memory_id",
                error="missing_memory_id",
            )
        directory = memory_dir(context)
        matches: list[dict[str, Any]] = []
        if directory.exists():
            for path in sorted(directory.glob("*.jsonl")):
                for entry in read_memory_entries_tolerant(path, context.validator):
                    if str(entry.get("memory_id", "")) == wanted:
                        matches.append({**entry, "source_file": path.name})
        if not matches:
            return ToolResult(
                ok=False,
                summary=f"No memory entry found with id {wanted}",
                error="memory_not_found",
            )
        return ToolResult(
            ok=True,
            summary=f"Recalled {len(matches)} memory entr{'y' if len(matches) == 1 else 'ies'} for {wanted}",
            data={"matches": matches},
        )
