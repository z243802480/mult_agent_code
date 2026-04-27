from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_runtime.storage.schema_validator import SchemaValidator


class JsonStore:
    def __init__(self, validator: SchemaValidator | None = None) -> None:
        self.validator = validator

    def read(self, path: Path, schema_name: str | None = None) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        return data

    def write(self, path: Path, data: dict[str, Any], schema_name: str | None = None) -> None:
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
