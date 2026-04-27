from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    pass


class SchemaValidator:
    """Small JSON Schema subset validator for MVP boundary checks.

    It intentionally supports the subset used by this project schemas:
    type, required, properties, items, enum, anyOf, and additionalProperties.
    This avoids making runtime initialization depend on an installed third-party package.
    """

    def __init__(self, schema_dir: Path) -> None:
        self.schema_dir = schema_dir
        self._cache: dict[str, dict[str, Any]] = {}

    def validate(self, schema_name: str, data: Any) -> None:
        schema = self._load(schema_name)
        self._validate_node(schema, data, path="$")

    def _load(self, schema_name: str) -> dict[str, Any]:
        if schema_name not in self._cache:
            path = self.schema_dir / f"{schema_name}.schema.json"
            if not path.exists():
                raise SchemaValidationError(f"Schema not found: {path}")
            self._cache[schema_name] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[schema_name]

    def _validate_node(self, schema: dict[str, Any], data: Any, path: str) -> None:
        if "anyOf" in schema:
            errors = []
            for option in schema["anyOf"]:
                try:
                    self._validate_node(option, data, path)
                    return
                except SchemaValidationError as exc:
                    errors.append(str(exc))
            raise SchemaValidationError(f"{path}: did not match any allowed schema: {errors}")

        if "type" in schema:
            self._validate_type(schema["type"], data, path)

        if "enum" in schema and data not in schema["enum"]:
            raise SchemaValidationError(f"{path}: expected one of {schema['enum']}, got {data!r}")

        if isinstance(data, dict):
            for key in schema.get("required", []):
                if key not in data:
                    raise SchemaValidationError(f"{path}: missing required key {key!r}")
            properties = schema.get("properties", {})
            for key, value in data.items():
                if key in properties:
                    self._validate_node(properties[key], value, f"{path}.{key}")
                elif schema.get("additionalProperties") is False:
                    raise SchemaValidationError(f"{path}: unexpected key {key!r}")

        if isinstance(data, list) and "items" in schema:
            for index, item in enumerate(data):
                self._validate_node(schema["items"], item, f"{path}[{index}]")

    def _validate_type(self, expected: str | list[str], data: Any, path: str) -> None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if any(self._matches_type(item, data) for item in expected_types):
            return
        raise SchemaValidationError(f"{path}: expected type {expected_types}, got {type(data).__name__}")

    def _matches_type(self, expected: str, data: Any) -> bool:
        return {
            "object": isinstance(data, dict),
            "array": isinstance(data, list),
            "string": isinstance(data, str),
            "integer": isinstance(data, int) and not isinstance(data, bool),
            "number": (isinstance(data, int | float) and not isinstance(data, bool)),
            "boolean": isinstance(data, bool),
            "null": data is None,
        }.get(expected, False)
