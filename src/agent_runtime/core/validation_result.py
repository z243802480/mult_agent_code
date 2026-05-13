from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.core.runtime_profile import SCHEMA_VERSION


@dataclass(frozen=True)
class ValidationResult:
    validation_result_id: str
    run_id: str | None
    task_id: str
    tool_name: str
    status: str
    summary: str
    created_at: str
    command: str | None = None
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "validation_result_id": self.validation_result_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "command": self.command,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "data": self.data,
            "created_at": self.created_at,
        }
