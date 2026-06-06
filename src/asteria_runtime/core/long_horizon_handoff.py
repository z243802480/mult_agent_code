from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


HANDOFF_REL = Path(".asteria") / "long_horizon_handoff.json"


def handoff_path(root: Path) -> Path:
    return root.resolve() / HANDOFF_REL


def _compact_active_goal(memory: dict[str, Any]) -> dict[str, Any]:
    if not memory:
        return {}
    return {
        "current_goal": memory.get("current_goal"),
        "completion": (memory.get("current_result") or {}).get("completion"),
        "blockers": list(memory.get("current_blockers") or [])[:5],
        "next_task": list(memory.get("next_task") or [])[:3],
        "watch_items": list(memory.get("watch_items") or [])[:3],
        "source_run_id": memory.get("source_run_id"),
    }


def _build_narrative(
    *,
    north_star_ref: dict[str, Any] | None,
    slice_completion: dict[str, Any] | None,
    active_goal_summary: dict[str, Any],
    continue_hint: dict[str, Any] | None,
) -> str:
    parts: list[str] = []
    if north_star_ref:
        title = str(north_star_ref.get("title") or "").strip()
        milestone = str(north_star_ref.get("active_milestone") or "").strip()
        if title:
            parts.append(f"North Star：{title}")
        if milestone:
            parts.append(f"当前 milestone：{milestone}")
    if slice_completion:
        parts.append(str(slice_completion.get("summary") or "").strip())
    completion = str(active_goal_summary.get("completion") or "").strip()
    if completion:
        parts.append(f"最近结果：{completion}")
    blockers = active_goal_summary.get("blockers") or []
    if blockers:
        parts.append(f"阻塞：{'; '.join(str(item) for item in blockers[:2])}")
    if continue_hint:
        parts.append(f"下一步队列：{continue_hint.get('goal_text')}")
    return "\n".join(part for part in parts if part)


def build_long_horizon_handoff(
    root: Path,
    *,
    trigger_run_id: str,
    slice_completion_eval: dict[str, Any] | None = None,
    goal_queue_continue: dict[str, Any] | None = None,
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    north_star_ref = NorthStarStore(root).summary_for_status() or {}
    if north_star_link and north_star_link.get("milestone_id"):
        north_star_ref = dict(north_star_ref)
        north_star_ref["linked_milestone_id"] = north_star_link.get("milestone_id")
    memory = ActiveGoalMemory(root).read_structured()
    active_goal_summary = _compact_active_goal(memory)
    slice_payload = None
    if slice_completion_eval:
        slice_payload = {
            "run_id": slice_completion_eval.get("run_id"),
            "slice_complete": slice_completion_eval.get("slice_complete"),
            "summary": slice_completion_eval.get("summary"),
            "north_star_milestone_id": slice_completion_eval.get("north_star_milestone_id"),
        }
    narrative = _build_narrative(
        north_star_ref=north_star_ref,
        slice_completion=slice_payload,
        active_goal_summary=active_goal_summary,
        continue_hint=goal_queue_continue,
    )
    recommended = None
    if goal_queue_continue and goal_queue_continue.get("command"):
        recommended = str(goal_queue_continue["command"])
    return {
        "schema_version": "0.1.0",
        "updated_at": now_iso(),
        "trigger_run_id": trigger_run_id,
        "north_star_ref": north_star_ref,
        "slice_completion": slice_payload,
        "continue_hint": goal_queue_continue,
        "active_goal_summary": active_goal_summary,
        "narrative": narrative or "Long-horizon handoff updated.",
        "recommended_next_command": recommended,
    }


def persist_long_horizon_handoff(
    root: Path,
    payload: dict[str, Any],
    validator: SchemaValidator | None = None,
) -> Path:
    validator = validator or SchemaValidator(schema_dir())
    path = handoff_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    JsonStore(validator).write(path, payload, "long_horizon_handoff")
    return path


def build_and_persist_long_horizon_handoff(
    root: Path,
    *,
    trigger_run_id: str,
    validator: SchemaValidator | None = None,
    slice_completion_eval: dict[str, Any] | None = None,
    goal_queue_continue: dict[str, Any] | None = None,
    north_star_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_long_horizon_handoff(
        root,
        trigger_run_id=trigger_run_id,
        slice_completion_eval=slice_completion_eval,
        goal_queue_continue=goal_queue_continue,
        north_star_link=north_star_link,
    )
    persist_long_horizon_handoff(root, payload, validator)
    return payload


def read_long_horizon_handoff(root: Path, validator: SchemaValidator | None = None) -> dict[str, Any] | None:
    path = handoff_path(root)
    if not path.exists():
        return None
    validator = validator or SchemaValidator(schema_dir())
    try:
        payload = JsonStore(validator).read(path, "long_horizon_handoff")
    except Exception:  # noqa: BLE001
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return payload if isinstance(payload, dict) else None


def handoff_compact_projection(root: Path, validator: SchemaValidator | None = None) -> dict[str, Any]:
    payload = read_long_horizon_handoff(root, validator)
    if not payload:
        return {
            "available": False,
            "summary": "No long-horizon handoff compact recorded yet.",
            "path": str(HANDOFF_REL).replace("\\", "/"),
        }
    continue_hint = payload.get("continue_hint") if isinstance(payload.get("continue_hint"), dict) else {}
    slice_completion = (
        payload.get("slice_completion") if isinstance(payload.get("slice_completion"), dict) else {}
    )
    return {
        "available": True,
        "updated_at": payload.get("updated_at"),
        "trigger_run_id": payload.get("trigger_run_id"),
        "narrative": payload.get("narrative"),
        "recommended_next_command": payload.get("recommended_next_command"),
        "continue_goal": continue_hint.get("goal_text"),
        "slice_complete": slice_completion.get("slice_complete"),
        "path": str(HANDOFF_REL).replace("\\", "/"),
    }
