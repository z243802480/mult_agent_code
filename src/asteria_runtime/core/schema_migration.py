from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable


MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SchemaMigration:
    """A single migration step from one schema version to the next."""

    schema_name: str
    from_version: str
    to_version: str
    migrate: MigrationFn
    description: str = ""


@dataclass
class MigrationRecord:
    """Audit trail entry for a completed migration."""

    schema_name: str
    from_version: str
    to_version: str
    description: str


class SchemaMigrationRegistry:
    """Registry of versioned schema migrations.

    Each schema (policy_config, runtime_hook_event, plugin_manifest) can have
    a chain of migrations. When data is loaded, the registry detects the current
    version and runs all applicable migrations in order.
    """

    def __init__(self) -> None:
        self._migrations: dict[str, list[SchemaMigration]] = {}
        self._history: list[MigrationRecord] = []

    def register(self, migration: SchemaMigration) -> None:
        migrations = self._migrations.setdefault(migration.schema_name, [])
        for existing in migrations:
            if existing.from_version == migration.from_version:
                raise ValueError(
                    f"Duplicate migration for {migration.schema_name} "
                    f"from {migration.from_version}"
                )
        migrations.append(migration)
        migrations.sort(key=lambda m: m.from_version)

    def migrate(
        self, schema_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Run all applicable migrations for the given schema."""
        current = deepcopy(data)
        version = str(current.get("schema_version", "0.0.0"))
        chain = self._migrations.get(schema_name, [])
        for migration in chain:
            if version == migration.from_version:
                current = migration.migrate(current)
                if current.get("schema_version") != migration.to_version:
                    current["schema_version"] = migration.to_version
                self._history.append(
                    MigrationRecord(
                        schema_name=schema_name,
                        from_version=migration.from_version,
                        to_version=migration.to_version,
                        description=migration.description,
                    )
                )
                version = migration.to_version
        return current

    @property
    def history(self) -> list[MigrationRecord]:
        return list(self._history)

    def latest_version(self, schema_name: str) -> str:
        chain = self._migrations.get(schema_name, [])
        if not chain:
            return ""
        return chain[-1].to_version

    def migration_chain(self, schema_name: str) -> list[tuple[str, str]]:
        return [
            (m.from_version, m.to_version)
            for m in self._migrations.get(schema_name, [])
        ]


def build_default_registry() -> SchemaMigrationRegistry:
    """Build a registry with all known schema migrations."""
    registry = SchemaMigrationRegistry()

    # policy_config: 0.1.0 -> 0.2.0
    # Adds feature_flags and capability_flags sections.
    registry.register(
        SchemaMigration(
            schema_name="policy_config",
            from_version="0.1.0",
            to_version="0.2.0",
            migrate=_policy_010_to_020,
            description="Add feature_flags and capability_flags top-level sections.",
        )
    )

    # policy_config: 0.2.0 -> 0.3.0
    # Adds provider route strategy thresholds for strong goal specification.
    registry.register(
        SchemaMigration(
            schema_name="policy_config",
            from_version="0.2.0",
            to_version="0.3.0",
            migrate=_policy_020_to_030,
            description="Add provider route strategy thresholds.",
        )
    )

    # plugin_manifest: 0.1.0 -> 0.2.0
    # Adds blocked_reason and loaded_at fields.
    registry.register(
        SchemaMigration(
            schema_name="plugin_manifest",
            from_version="0.1.0",
            to_version="0.2.0",
            migrate=_plugin_010_to_020,
            description="Add blocked_reason and loaded_at optional fields.",
        )
    )

    return registry


def _policy_010_to_020(data: dict[str, Any]) -> dict[str, Any]:
    feature_flags = data.setdefault("feature_flags", {})
    feature_flags.setdefault(
        "streaming",
        {
            "enabled": True,
            "description": "Enable provider streaming requests and first-token telemetry.",
            "requires": ["provider_streaming"],
        },
    )
    data.setdefault("capability_flags", {})
    return data


def _policy_020_to_030(data: dict[str, Any]) -> dict[str, Any]:
    strategy = data.setdefault("provider_route_strategy", {})
    strong_goal_spec = strategy.setdefault("strong_goal_spec", {})
    strong_goal_spec.setdefault("primary_model", "glm-5")
    strong_goal_spec.setdefault("cost_saver_model", "glm-4.7")
    strong_goal_spec.setdefault("min_calls_before_enforcement", 3)
    strong_goal_spec.setdefault("min_success_rate_for_validation", 0.8)
    strong_goal_spec.setdefault("max_timeout_failures_for_validation", 1)
    strong_goal_spec.setdefault("provider_deadline_seconds", 120)
    strong_goal_spec.setdefault("stream_idle_timeout_seconds", 30)
    strong_goal_spec.setdefault(
        "continue_primary_when",
        [
            "release gate is being refreshed",
            "route guidance is healthy",
            "recent success rate is at or above min_success_rate_for_validation",
        ],
    )
    strong_goal_spec.setdefault(
        "allow_cost_saver_when",
        [
            "task is a small validation task",
            "cost budget is constrained",
            "cost_saver recent success rate is at or above min_success_rate_for_validation",
        ],
    )
    strong_goal_spec.setdefault(
        "downgrade_or_retry_when",
        [
            "primary route is transiently rate limited",
            "primary route hits one timeout but recent success rate remains acceptable",
            "task is doc-only or low-risk and medium route is healthy",
        ],
    )
    strong_goal_spec.setdefault(
        "block_validation_when",
        [
            "strong goal_spec success rate is below min_success_rate_for_validation after min_calls_before_enforcement calls",
            "timeout failures exceed max_timeout_failures_for_validation",
            "authentication, budget, or configuration failure is present",
            "provider streaming evidence is missing for required strong and medium routes",
        ],
    )
    return data


def _plugin_010_to_020(data: dict[str, Any]) -> dict[str, Any]:
    data.setdefault("blocked_reason", "")
    data.setdefault("loaded_at", "")
    return data
