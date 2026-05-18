from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class LoadedPluginManifest:
    path: Path
    manifest: dict[str, Any]
    status: str
    reason: str

    @property
    def plugin_id(self) -> str:
        return str(self.manifest.get("plugin_id") or self.path.stem)

    @property
    def executable(self) -> bool:
        return self.status == "enabled"


class PluginManifestLoader:
    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator
        self.store = JsonStore(validator)

    def load(self, agent_dir: Path, policy: dict[str, Any]) -> list[LoadedPluginManifest]:
        plugin_dir = agent_dir / "plugins"
        if not plugin_dir.exists():
            return []
        raw_hooks_policy = policy.get("hooks")
        hooks_policy: dict[str, Any] = (
            raw_hooks_policy if isinstance(raw_hooks_policy, dict) else {}
        )
        plugins_enabled = bool(hooks_policy.get("plugins_enabled", False))
        allowed_hooks = set(hooks_policy.get("allowed_hook_names") or [])
        loaded = []
        for path in sorted(plugin_dir.glob("*.plugin.json")):
            manifest = self.store.read(path, "plugin_manifest")
            loaded.append(self._classify(path, manifest, plugins_enabled, allowed_hooks))
        return loaded

    def _classify(
        self,
        path: Path,
        manifest: dict[str, Any],
        plugins_enabled: bool,
        allowed_hooks: set[str],
    ) -> LoadedPluginManifest:
        unknown_hooks = sorted(set(manifest.get("hook_subscriptions") or []) - allowed_hooks)
        if unknown_hooks:
            return LoadedPluginManifest(
                path=path,
                manifest=manifest,
                status="blocked",
                reason=f"Unknown or disallowed hook subscriptions: {', '.join(unknown_hooks)}",
            )
        if not plugins_enabled:
            return LoadedPluginManifest(
                path=path,
                manifest=manifest,
                status="disabled",
                reason="Plugin execution is disabled by hooks.plugins_enabled.",
            )
        if not manifest.get("enabled"):
            return LoadedPluginManifest(
                path=path,
                manifest=manifest,
                status="disabled",
                reason="Plugin manifest is disabled.",
            )
        return LoadedPluginManifest(
            path=path,
            manifest=manifest,
            status="enabled",
            reason="Plugin manifest is eligible for handler registration.",
        )
