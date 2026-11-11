"""Bounded file observations with ranges that describe text the model actually sees."""

from __future__ import annotations

from typing import Any


def render_file_read(data: dict[str, Any], *, max_chars: int) -> str:
    content = data.get("content")
    if not isinstance(content, str):
        return ""  # Missing content is not evidence of an empty file.
    start = max(1, int(data.get("line_start") or 1))
    raw_total = data.get("total_lines")
    total = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0 else None
    total_label = str(total) if total is not None else "unknown"
    lines = content.splitlines()
    # A byte-bounded read may already end mid-line before the character renderer runs.
    partial_tail = bool(data.get("byte_truncated")) and not content.endswith("\n")

    def partial_notice(line: int) -> str:
        return (
            f"[partial_line={line}; not fully read. Line-based offset/limit cannot recover "
            "the rest of this line; inspect a targeted part with an appropriate available tool.]"
        )

    if not lines:
        if partial_tail:
            text = f"(no text visible at line {start})\n{partial_notice(start)}"
        elif total == 0:
            text = "(empty file; total_lines=0)"
        else:
            text = f"(no lines at offset={start}; total_lines={total_label})"
        return text[:max_chars]

    source_end = start + len(lines) - 1
    source_more = bool(data.get("has_more")) or (total is not None and source_end < total)

    def present(shown: list[str], *, partial: bool = False) -> str:
        end = start + len(shown) - 1
        header = f"(visible lines {start}-{end} of {total_label})\n"
        if partial:
            footer = "\n" + partial_notice(end)
        elif len(shown) < len(lines) or source_more:
            footer = (
                f"\n[More file text is not shown; next_offset={end + 1}. "
                f"Call read_file with offset={end + 1} (1-based).]"
            )
        else:
            footer = ""
        return header + "\n".join(shown) + footer

    numbered = [f"{start + i}\t{line}" for i, line in enumerate(lines)]
    whole = present(numbered, partial=partial_tail)
    if len(whole) <= max_chars:
        return whole

    # Keep complete lines; the next offset is the first line never displayed.
    shown: list[str] = []
    for i, line in enumerate(numbered):
        candidate = [*shown, line]
        partial = partial_tail and i == len(numbered) - 1
        if len(present(candidate, partial=partial)) > max_chars:
            break
        shown = candidate
    if shown:
        return present(shown, partial=partial_tail and len(shown) == len(numbered))

    # Even one line does not fit. Show its prefix but never advance past unread text.
    prefix = f"{start}\t"
    overhead = len(present([prefix], partial=True))
    if overhead > max_chars:
        return "(file output omitted: insufficient space for its range)"[:max_chars]
    return present([prefix + lines[0][:max_chars - overhead]], partial=True)
