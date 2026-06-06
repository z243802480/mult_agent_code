from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


class GoalQueueStore:
    """Bounded North Star goal queue (.asteria/goal_queue.json)."""

    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(schema_dir())
        self.store = JsonStore(self.validator)

    @property
    def path(self) -> Path:
        return self.root / ".asteria" / "goal_queue.json"

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        payload = self.store.read(self.path, "goal_queue")
        return payload if isinstance(payload, dict) else None

    def write(self, data: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload.setdefault("schema_version", "0.1.0")
        payload["updated_at"] = now_iso()
        self.store.write(self.path, payload, "goal_queue")
        return self.path

    def ensure_seeded_from_north_star(self) -> dict[str, Any] | None:
        existing = self.read()
        if existing and existing.get("items"):
            return existing
        north_star = NorthStarStore(self.root, self.validator).read()
        if not north_star:
            return existing
        pending_titles = [
            str(item.get("title") or "").strip()
            for item in north_star.get("milestones") or []
            if isinstance(item, dict)
            and str(item.get("status") or "") in {"pending", "in_progress"}
            and str(item.get("title") or "").strip()
        ]
        if not pending_titles:
            return existing
        return self.seed_goals(pending_titles, source="north_star")

    def seed_goals(self, goals: list[str], *, source: str = "operator") -> dict[str, Any]:
        items = []
        for index, goal_text in enumerate(goals, start=1):
            text = goal_text.strip()
            if not text:
                continue
            items.append(
                {
                    "goal_id": f"gq-{index:04d}",
                    "goal_text": text,
                    "status": "pending",
                    "source": source,
                    "linked_run_ids": [],
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
            )
        created_at = now_iso()
        payload = {
            "schema_version": "0.1.0",
            "queue_id": "gq-0001",
            "status": "active",
            "max_items": max(8, len(items)),
            "items": items,
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.write(payload)
        return payload

    def next_pending(self) -> dict[str, Any] | None:
        data = self.ensure_seeded_from_north_star()
        if not data:
            return None
        for item in data.get("items") or []:
            if isinstance(item, dict) and item.get("status") == "pending":
                return item
        return None

    def mark_in_progress(self, goal_id: str) -> dict[str, Any] | None:
        data = self.ensure_seeded_from_north_star()
        if not data:
            return None
        for item in data.get("items") or []:
            if isinstance(item, dict) and item.get("goal_id") == goal_id:
                item["status"] = "in_progress"
                item["updated_at"] = now_iso()
                self.write(data)
                return item
        return None

    def mark_done_for_run(self, run_id: str) -> dict[str, Any] | None:
        data = self.ensure_seeded_from_north_star()
        if not data:
            return None
        items = data.get("items") or []
        target = None
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "in_progress":
                target = item
                break
        if target is None:
            for item in items:
                if isinstance(item, dict) and item.get("status") == "pending":
                    target = item
                    break
        if target is None:
            return None
        linked = [str(value) for value in (target.get("linked_run_ids") or []) if value]
        if run_id not in linked:
            linked.append(run_id)
        target["linked_run_ids"] = linked
        target["status"] = "done"
        target["updated_at"] = now_iso()
        self.write(data)
        return target

    def continue_hint(self) -> dict[str, Any] | None:
        next_item = self.next_pending()
        if not next_item:
            return None
        goal_text = str(next_item.get("goal_text") or "").strip()
        if not goal_text:
            return None
        return {
            "goal_id": next_item.get("goal_id"),
            "goal_text": goal_text,
            "command": f'goal "{goal_text}"',
            "label": "Continue North Star slice",
        }
