from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_runtime.storage.schema_validator import SchemaValidator


class JsonlStore:
    def __init__(self, validator: SchemaValidator | None = None) -> None:
        self.validator = validator

    def append(self, path: Path, data: dict[str, Any], schema_name: str | None = None) -> None:
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    def read_all(self, path: Path, schema_name: str | None = None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc
                if schema_name and self.validator:
                    self.validator.validate(schema_name, data)
                rows.append(data)
        return rows
