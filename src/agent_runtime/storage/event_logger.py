from __future__ import annotations

from pathlib import Path

from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class EventLogger:
    def __init__(self, events_path: Path, validator: SchemaValidator | None = None) -> None:
        self.events_path = events_path
        self.store = JsonlStore(validator)
        self._counter = self._load_existing_count()

    def record(
        self,
        run_id: str | None,
        event_type: str,
        actor: str,
        summary: str,
        data: dict | None = None,
    ) -> dict:
        self._counter += 1
        event = {
            "schema_version": "0.1.0",
            "event_id": f"event-{self._counter:04d}",
            "run_id": run_id,
            "timestamp": now_iso(),
            "type": event_type,
            "actor": actor,
            "summary": summary,
            "data": data or {},
        }
        self.store.append(self.events_path, event, "event")
        return event

    def read_all(self) -> list[dict]:
        return self.store.read_all(self.events_path, "event")

    def _load_existing_count(self) -> int:
        if not self.events_path.exists():
            return 0
        return len(JsonlStore().read_all(self.events_path))
