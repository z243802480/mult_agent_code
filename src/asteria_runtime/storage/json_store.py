from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from asteria_runtime.storage.schema_validator import SchemaValidator


_JSON_STORE_LOCK = RLock()


class JsonStore:
    def __init__(self, validator: SchemaValidator | None = None) -> None:
        self.validator = validator

    def read(self, path: Path, schema_name: str | None = None) -> dict[str, Any]:
        with _JSON_STORE_LOCK:
            data = json.loads(path.read_text(encoding="utf-8"))
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        return data

    def write(self, path: Path, data: dict[str, Any], schema_name: str | None = None) -> None:
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        with _JSON_STORE_LOCK:
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)
