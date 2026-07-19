from __future__ import annotations

from typing import Any

_PLAN_QUALITY_LABELS = {
    "pass": "良好",
    "warn": "需留意",
    "fail": "未达标",
}

_TRANSCRIPT_KINDS_FOR_STATUS = ("plan", "tool_use", "tool_result", "verification", "final", "stop")


def latest_main_transcript_event(
    events: list[dict[str, Any]],
    transcript_kind: str,
) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("display_level") == "inspector":
            continue
        if event.get("transcript_kind") == transcript_kind:
            return event
    return None


def latest_main_plan_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return latest_main_transcript_event(events, "plan")


def latest_main_tool_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    tool_use = latest_main_transcript_event(events, "tool_use")
    if tool_use:
        return tool_use
    return latest_main_transcript_event(events, "tool_result")


def latest_main_verification_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return latest_main_transcript_event(events, "verification")


def latest_main_final_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    final_event = latest_main_transcript_event(events, "final")
    if final_event:
        return final_event
    return latest_main_transcript_event(events, "stop")


def build_plan_completion_copy(
    *,
    task_count: int,
    task_titles: list[str],
    quality_status: str,
    quality_score: float | None = None,
) -> tuple[str, str]:
    title = "计划已生成"
    parts = [f"共 {task_count} 个任务"]
    preview_titles = [text for text in task_titles if text][:3]
    if preview_titles:
        preview = "、".join(preview_titles)
        if len(task_titles) > len(preview_titles):
            preview = f"{preview} 等 {task_count} 项"
        parts.append(f"包括：{preview}")
    quality_label = _PLAN_QUALITY_LABELS.get(str(quality_status).lower(), quality_status)
    # Show the plain-language status only — NOT the raw overall_score (F6). The evaluator sets "warn"
    # whenever there are ANY issues, independent of the score (task_plan_evaluator._status), so a plan
    # can score 0.98 and still be "需留意" — pairing "需留意" with "0.98" reads as a contradiction to the
    # user (dogfood: "计划质量：需留意（0.98）"). The exact score + issue list stay in the "计划质量核对"
    # evidence event (Inspector); the main thread gets the actionable label. quality_score is accepted
    # for call-site compatibility but deliberately not rendered.
    _ = quality_score
    parts.append(f"计划质量：{quality_label}")
    return title, "；".join(parts) + "。"


def build_transcript_runtime_progress(
    event: dict[str, Any] | None,
    *,
    transcript_kind: str,
    task_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not event:
        return None
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    task_count = int((task_summary or {}).get("total") or 0) or int(data.get("task_count") or 0)
    payload: dict[str, Any] = {
        "transcript_kind": transcript_kind,
        "ui_intent": event.get("ui_intent") or "work_progress",
        "phase": event.get("phase"),
        "status": event.get("status"),
        "title": event.get("title"),
        "summary": event.get("summary"),
        "content_delta": event.get("content_delta") or "",
        "event_id": event.get("event_id"),
        "created_at": event.get("created_at"),
    }
    if task_count:
        payload["task_count"] = task_count
    if event.get("tool_call_id"):
        payload["tool_call_id"] = event.get("tool_call_id")
    return payload


def build_plan_runtime_progress(
    event: dict[str, Any] | None,
    *,
    task_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return build_transcript_runtime_progress(
        event,
        transcript_kind="plan",
        task_summary=task_summary,
    )


def build_user_progress_projections(
    events: list[dict[str, Any]],
    *,
    task_summary: dict[str, Any] | None = None,
) -> dict[str, Any | None]:
    tool_event = latest_main_tool_event(events)
    tool_kind = str(tool_event.get("transcript_kind") or "tool_use") if tool_event else "tool_use"
    final_event = latest_main_final_event(events)
    final_kind = str(final_event.get("transcript_kind") or "final") if final_event else "final"
    return {
        "plan": build_plan_runtime_progress(
            latest_main_plan_event(events),
            task_summary=task_summary,
        ),
        "tool": build_transcript_runtime_progress(tool_event, transcript_kind=tool_kind),
        "verify": build_transcript_runtime_progress(
            latest_main_verification_event(events),
            transcript_kind="verification",
        ),
        "final": build_transcript_runtime_progress(final_event, transcript_kind=final_kind),
    }


def required_main_transcript_kinds(events: list[dict[str, Any]]) -> set[str]:
    kinds: set[str] = set()
    for event in events:
        if event.get("display_level") == "inspector":
            continue
        kind = str(event.get("transcript_kind") or "")
        if kind in _TRANSCRIPT_KINDS_FOR_STATUS:
            kinds.add(kind)
    return kinds
