from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass
class RuntimeContext:
    root: Path
    run_id: str | None
    policy: dict
    validator: SchemaValidator
    event_logger: EventLogger | None = None
    budget: BudgetController | None = None

    @property
    def agent_dir(self) -> Path:
        return self.root / ".agent"

    @property
    def run_dir(self) -> Path | None:
        if self.run_id is None:
            return None
        return self.agent_dir / "runs" / self.run_id

    def tool_call_store(self) -> JsonlStore | None:
        if self.run_dir is None:
            return None
        return JsonlStore(self.validator)
