"""Cross-attempt task progress digest (ADR-0016 boundary, not cognition).

A model-driven task turn accumulates its observations in the live message history, but that history
is thrown away when the turn ends. So when a read-heavy task trips the iteration fuse
(``budget_exhausted``) or a user pauses/resumes it, the *next* attempt starts from a blank prompt and
re-reads every file from scratch — the model spends its budget re-navigating instead of finishing
(dogfood residual②, run-20260718; the fuse-headroom half is 1.2.126, this is the persistence half).

This module keeps a compact, bounded, on-disk ledger of *what the model already did* for a task —
files read, commands run, searches made, writes landed — keyed by task_id under the run dir. Because
it lives on disk it bridges BOTH an in-process replan and a cross-process ``asteria resume``. It is a
memory/context boundary: the harness carries forward the fact that "you already looked at X"; the
model still decides what to do with it (ADR-0016 — cognition stays with the model). It complements
the goal-level ``ActiveGoalMemory`` (which tracks tasks/artifacts, not per-attempt tool actions).

Only one-line action summaries are stored (never the full file content that blew the budget in the
first place) — enough for the model to know it need not re-read, cheap enough to never itself be the
thing that fills the window. The full output remains in run evidence (tool_calls.jsonl).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

_DIGEST_DIR = "task_progress"
#: Keep the most recent N distinct actions. A task that legitimately touches more than this many
#: distinct files/commands is rare; when it happens the oldest (already-superseded) actions are the
#: safest to drop, and the note below tells the model the list was trimmed.
_MAX_ENTRIES = 40
#: Hard cap on a single entry so one pathological summary cannot bloat the digest.
_MAX_ENTRY_CHARS = 240


def _safe_task_id(task_id: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(task_id)) or "task"


def _digest_path(run_dir: Path, task_id: str) -> Path:
    return run_dir / _DIGEST_DIR / f"{_safe_task_id(task_id)}.json"


def _entry_for(obs: Any) -> str | None:
    """One-line, model-facing record of a single tool action. Uses the observation's own summary
    (already a compact human string like "Read file: cli.py (lines 690-729 of 2502)") rather than
    digging into tool-specific ``data`` keys, so it stays robust across tools. Failed actions are
    marked so the model does not blindly repeat an approach that already failed."""
    name = str(getattr(obs, "tool_name", "") or "").strip()
    summary = str(getattr(obs, "summary", "") or "").strip()
    if not name or not summary:
        return None
    marker = "" if getattr(obs, "ok", True) else " [failed]"
    entry = f"{name}{marker}: {summary}"
    if len(entry) > _MAX_ENTRY_CHARS:
        entry = entry[: _MAX_ENTRY_CHARS - 1].rstrip() + "…"
    return entry


def _load_entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    return [str(item) for item in entries if isinstance(item, str) and item.strip()]


def record_task_progress(
    run_dir: Path | None, task_id: str, observations: Iterable[Any]
) -> None:
    """Merge this attempt's tool actions into the task's on-disk digest (dedup, bounded, most-recent
    kept). Best-effort: a digest write must never abort a task, so all I/O errors are swallowed."""
    if run_dir is None or not task_id:
        return
    new_entries = [entry for obs in observations if (entry := _entry_for(obs))]
    if not new_entries:
        return
    path = _digest_path(run_dir, task_id)
    existing = _load_entries(path)
    seen = set(existing)
    for entry in new_entries:
        if entry not in seen:
            existing.append(entry)
            seen.add(entry)
    trimmed = existing[-_MAX_ENTRIES:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"task_id": task_id, "entries": trimmed}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        return


def load_task_progress(run_dir: Path | None, task_id: str) -> list[str]:
    """The task's prior-attempt action entries (empty on the first attempt → callers inject nothing,
    so behaviour is byte-identical to before whenever no prior attempt ran)."""
    if run_dir is None or not task_id:
        return []
    return _load_entries(_digest_path(run_dir, task_id))


def render_prior_progress(entries: list[str]) -> str | None:
    """A prompt block telling the model what it already accomplished on THIS task in earlier
    attempt(s), so it continues instead of re-reading from scratch. None when there is nothing to
    carry (first attempt)."""
    if not entries:
        return None
    trimmed_note = ""
    if len(entries) >= _MAX_ENTRIES:
        trimmed_note = " (older actions were trimmed)"
    lines = [
        "You already worked on THIS task in an earlier attempt that did not finish (it hit the "
        "iteration budget or was paused). You DID the following already" + trimmed_note + " — do "
        "NOT redo this work; build on it and drive to completion. Re-read a file only if its "
        "contents may have changed since:",
        *[f"- {entry}" for entry in entries],
    ]
    return "\n".join(lines)
