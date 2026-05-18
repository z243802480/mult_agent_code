from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from asteria_runtime.core.schema_migration import SchemaMigrationRegistry, build_default_registry
from asteria_runtime.resources import template_path
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator, SchemaValidationError


def load_policy_config(
    agent_dir: Path,
    validator: SchemaValidator,
    migration_registry: SchemaMigrationRegistry | None = None,
) -> dict:
    path = agent_dir / "policies.json"
    store = JsonStore(validator)
    registry = migration_registry or build_default_registry()
    try:
        data = store.read(path, "policy_config")
        return registry.migrate("policy_config", data)
    except SchemaValidationError:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        migrated = registry.migrate("policy_config", merge_policy_defaults(current))
        store.write(path, migrated, "policy_config")
        return migrated


def merge_policy_defaults(current: dict[str, Any]) -> dict:
    default = json.loads(_default_policy_path().read_text(encoding="utf-8"))
    merged = _deep_merge(default, current)
    return merged


def _deep_merge(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(default)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_policy_path() -> Path:
    return template_path("policies.default.json")
