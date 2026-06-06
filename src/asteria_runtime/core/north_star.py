from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


class NorthStarStore:
    """Workspace-local North Star persistence (.asteria/north_star.json)."""

    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(schema_dir())
        self.store = JsonStore(self.validator)

    @property
    def path(self) -> Path:
        return self.root / ".asteria" / "north_star.json"

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return self.store.read(self.path, "north_star")

    def write(self, data: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload.setdefault("schema_version", "0.1.0")
        payload["updated_at"] = now_iso()
        self.store.write(self.path, payload, "north_star")
        return self.path

    def create_default(
        self,
        *,
        title: str,
        statement: str,
        horizon: str = "year",
        milestone_titles: list[str] | None = None,
        updated_by: str = "init",
    ) -> Path:
        titles = milestone_titles or [
            "Harness 会话 MVP 稳定",
            "North Star 跨 run 里程碑",
            "Studio 长期目标可见",
        ]
        milestones = [
            {
                "milestone_id": f"ms-{index + 1:04d}",
                "title": item,
                "summary": item,
                "status": "in_progress" if index == 0 else "pending",
                "linked_run_ids": [],
                "acceptance": [f"Evidence recorded for: {item}"],
                "updated_at": now_iso(),
            }
            for index, item in enumerate(titles)
        ]
        created_at = now_iso()
        return self.write(
            {
                "schema_version": "0.1.0",
                "north_star_id": "ns-0001",
                "title": title.strip(),
                "statement": statement.strip(),
                "horizon": horizon,
                "status": "active",
                "milestones": milestones,
                "non_goals": ["蜂群 parallel write", "无策略自动 execute"],
                "created_at": created_at,
                "updated_at": created_at,
                "updated_by": updated_by,
            }
        )

    def link_run(self, run_id: str, *, milestone_id: str | None = None) -> dict[str, Any] | None:
        data = self.read()
        if not data:
            return None
        milestones = data.get("milestones")
        if not isinstance(milestones, list):
            return None
        target = self._select_milestone(milestones, milestone_id)
        if target is None:
            return None
        linked = [
            str(item)
            for item in (target.get("linked_run_ids") or [])
            if item
        ]
        if run_id not in linked:
            linked.append(run_id)
        target["linked_run_ids"] = linked
        if target.get("status") == "pending":
            target["status"] = "in_progress"
        if len(linked) >= 3 and target.get("status") == "in_progress":
            target["status"] = "completed"
        target["updated_at"] = now_iso()
        self.write(data)
        return {
            "milestone_id": target.get("milestone_id"),
            "title": target.get("title"),
            "status": target.get("status"),
            "linked_run_ids": linked,
        }

    def summary_for_status(self) -> dict[str, Any] | None:
        data = self.read()
        if not data:
            return None
        milestones = [
            item for item in (data.get("milestones") or []) if isinstance(item, dict)
        ]
        active = self._active_milestone(milestones)
        completed = len([item for item in milestones if item.get("status") == "completed"])
        return {
            "north_star_id": data.get("north_star_id"),
            "title": data.get("title"),
            "statement": data.get("statement"),
            "horizon": data.get("horizon"),
            "status": data.get("status"),
            "active_milestone": active.get("title") if active else None,
            "active_milestone_id": active.get("milestone_id") if active else None,
            "milestone_count": len(milestones),
            "completed_milestones": completed,
            "path": str(self.path.relative_to(self.root)).replace("\\", "/")
            if self.path.exists()
            else None,
        }

    def _select_milestone(
        self,
        milestones: list[Any],
        milestone_id: str | None,
    ) -> dict[str, Any] | None:
        if milestone_id:
            for item in milestones:
                if isinstance(item, dict) and item.get("milestone_id") == milestone_id:
                    return item
            return None
        active = self._active_milestone(milestones)
        if active is not None:
            return active
        for item in milestones:
            if isinstance(item, dict) and item.get("status") == "pending":
                return item
        return None

    def _active_milestone(self, milestones: list[Any]) -> dict[str, Any] | None:
        for item in milestones:
            if isinstance(item, dict) and item.get("status") == "in_progress":
                return item
        return None
