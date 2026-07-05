"""Model-authored closing recap for a finished run (CV-C).

Today the runtime only emits short/structured conclusion fragments
("Run X 已完成，状态：completed。共 N 个执行步骤。"). The Studio main thread
renders those verbatim (ADR-0012: the thread only shows real transcript text and
never fabricates the final answer), so the closing reply reads like a status line
rather than a conversational recap from the agent.

This module lets the agent *author* a 1–3 sentence first-person recap with one
extra, best-effort model call. The text is returned to the caller, which stores it
as the ``content_delta`` of the existing ``conclusion`` transcript event — so the
recap is the agent's own prose, displayed verbatim, with no client-side synthesis.

Best-effort by design: when no model client is available or the call fails, this
returns ``""`` and the caller falls back to the existing structured summary. The
run lifecycle never depends on the recap succeeding.
"""

from __future__ import annotations

import re
from typing import Any

from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient

RECAP_PURPOSE = "run_closing_recap"

_SYSTEM_PROMPT = (
    "You are Asteria, a coding agent that just finished a task for the user. "
    "Write a SHORT closing recap — 1 to 3 sentences — in the first person, exactly "
    "as you would say it at the end of a chat. Plain conversational prose only: no "
    "headings, no markdown sections, no bullet lists, no field labels like "
    "'Result:' or 'Verification:'. Say what you accomplished, whether the checks "
    "passed, and — only if it is genuinely useful — the single best next step. Be "
    "honest: if the run was blocked or verification failed, say so plainly. Match "
    "the language of the goal (reply in Chinese when the goal is in Chinese). Do not "
    "invent results that are not supported by the context below."
)

# Hard caps so a misbehaving model can never bloat the main thread.
_MAX_CHARS = 600
_MAX_STEPS = 12
_MAX_FILES = 12

# Reasoning models (e.g. MiniMax M2, the default medium tier) inline chain-of-thought in
# <think>…</think> before the answer, and burn output tokens doing it. The recap is the prose AFTER
# the reasoning — give enough headroom that the model finishes thinking AND writes the recap (320
# was too small: the whole budget went to thinking and the answer was never emitted).
_MAX_OUTPUT_TOKENS = 2048
_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def author_run_recap(
    *,
    model_client: ModelClient | None,
    goal: str,
    run_status: str,
    steps: list[tuple[str, str, str]],
    file_changes: list[dict[str, Any]],
    validation: dict[str, Any] | None,
    model_tier: str = "medium",
) -> str:
    """Return a 1–3 sentence conversational recap, or ``""`` on any failure.

    ``steps`` are ``(name, status, summary)`` tuples; ``validation`` is the dict
    produced by ``RunCommand._validation_conclusion`` (or ``None``).
    """
    if model_client is None:
        return ""
    context = _build_context(goal, run_status, steps, file_changes, validation)
    try:
        request = ChatRequest(
            purpose=RECAP_PURPOSE,
            model_tier=model_tier,
            messages=[
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=context),
            ],
            temperature=0.3,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            timeout_seconds=45,
            metadata={"agent_id": "RunRecap", "purpose": RECAP_PURPOSE},
        )
        response = model_client.chat(request)
    except Exception:  # noqa: BLE001 — recap is best-effort; never fail the run.
        return ""
    return _clean(getattr(response, "content", ""))


def _build_context(
    goal: str,
    run_status: str,
    steps: list[tuple[str, str, str]],
    file_changes: list[dict[str, Any]],
    validation: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    goal_text = str(goal or "").strip()
    lines.append(f"Goal: {goal_text or '(not recorded)'}")
    lines.append(f"Final run status: {run_status}")

    validation = validation or {}
    v_status = str(validation.get("status") or "not_recorded")
    v_passed = validation.get("passed")
    v_total = validation.get("total")
    if v_total:
        lines.append(f"Verification: {v_status} ({v_passed}/{v_total} checks passed)")
    else:
        lines.append(f"Verification: {v_status}")

    changed = [str(item.get("path") or "") for item in (file_changes or []) if item.get("path")]
    if changed:
        shown = changed[:_MAX_FILES]
        more = "" if len(changed) <= _MAX_FILES else f" (+{len(changed) - _MAX_FILES} more)"
        lines.append(f"Files changed ({len(changed)}): {', '.join(shown)}{more}")
    else:
        lines.append("Files changed: none recorded")

    if steps:
        lines.append("Loop steps:")
        for name, status, summary in steps[-_MAX_STEPS:]:
            detail = str(summary or "").strip().replace("\n", " ")
            if len(detail) > 160:
                detail = detail[:157] + "..."
            lines.append(f"- {name}: {status} — {detail}")

    lines.append(
        "\nWrite the closing recap now (1–3 sentences, conversational, no headings)."
    )
    return "\n".join(lines)


def _strip_reasoning(text: str) -> str:
    """Drop <think>…</think> chain-of-thought that reasoning models inline before the answer.

    Remove closed blocks; if only an unclosed <think> remains (the model spent its whole budget
    thinking and never wrote the recap), drop everything from that tag on so we return "" and fall
    back to the structured summary rather than leaking raw thinking into the main thread.
    """
    body = _THINK_BLOCK.sub("", text)
    lowered = body.lower()
    if "<think>" in lowered:
        body = body[: lowered.index("<think>")]
    return body.strip()


def _clean(text: str) -> str:
    """Strip reasoning + markdown scaffolding and clamp length so the recap stays conversational."""
    body = _strip_reasoning(str(text or "").strip())
    if not body:
        return ""
    cleaned_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Drop section headings and obvious field labels a stray model might emit.
        if line.startswith("#"):
            continue
        if line.lower().startswith(("result:", "recap:", "summary:", "verification:")):
            line = line.split(":", 1)[1].strip()
        line = line.lstrip("-* ").strip()
        if line:
            cleaned_lines.append(line)
    joined = " ".join(cleaned_lines).strip()
    if len(joined) > _MAX_CHARS:
        joined = joined[:_MAX_CHARS].rstrip() + "…"
    return joined
