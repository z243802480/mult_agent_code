from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class PluginsResult:
    action: str
    root: Path
    plugin_dir: Path
    hook_policy: dict[str, Any]
    plugins: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(plugin["status"] == "blocked" for plugin in self.plugins)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "action": self.action,
            "root": str(self.root),
            "plugin_dir": str(self.plugin_dir),
            "ok": self.ok,
            "summary": self.summary,
            "hook_policy": self.hook_policy,
            "plugins": self.plugins,
            "warnings": self.warnings,
        }

    def to_text(self) -> str:
        lines = [
            f"Plugin action: {self.action}",
            f"Plugin dir: {self.plugin_dir}",
            f"Summary: {self.summary}",
            (
                "Hook policy: "
                f"enabled={self.hook_policy.get('enabled')}, "
                f"plugins_enabled={self.hook_policy.get('plugins_enabled')}, "
                f"handler_timeout_ms={self.hook_policy.get('handler_timeout_ms')}"
            ),
        ]
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        if not self.plugins:
            lines.append("No plugin manifests.")
            return "\n".join(lines)
        lines.append("Plugins:")
        for plugin in self.plugins:
            lines.append(
                f"- {plugin['plugin_id']} [{plugin['status']}]: "
                f"manifest_enabled={plugin['manifest_enabled']} "
                f"subscriptions={','.join(plugin['hook_subscriptions']) or '-'}"
            )
            lines.append(f"  reason: {plugin['reason']}")
        return "\n".join(lines)


class PluginsCommand:
    def __init__(
        self,
        root: Path,
        action: str = "list",
        plugin_id: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.action = action
        self.plugin_id = plugin_id
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> PluginsResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
        if self.action in {"enable", "disable"}:
            self._set_enabled(agent_dir, self._require_plugin_id(), self.action == "enable")
        elif self.action not in {"list", "doctor"}:
            raise ValueError(f"Unsupported plugin action: {self.action}")
        summary = plugin_control_summary(self.root, self.validator)
        return PluginsResult(
            action=self.action,
            root=self.root,
            plugin_dir=Path(str(summary["plugin_dir"])),
            hook_policy=summary["hook_policy"],
            plugins=list(summary["plugins"]),
            summary=str(summary["summary"]),
            warnings=list(summary["warnings"]),
        )

    def to_json(self, result: PluginsResult) -> str:
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    def _set_enabled(self, agent_dir: Path, plugin_id: str, enabled: bool) -> None:
        path, manifest = self._find_manifest(agent_dir, plugin_id)
        updated = {**manifest, "enabled": enabled}
        self.store.write(path, updated, "plugin_manifest")

    def _find_manifest(self, agent_dir: Path, plugin_id: str) -> tuple[Path, dict[str, Any]]:
        plugin_dir = agent_dir / "plugins"
        for path in sorted(plugin_dir.glob("*.plugin.json")) if plugin_dir.exists() else []:
            manifest = self.store.read(path, "plugin_manifest")
            if manifest.get("plugin_id") == plugin_id:
                return path, manifest
        raise ValueError(f"plugin manifest not found: {plugin_id}")

    def _require_plugin_id(self) -> str:
        if not self.plugin_id:
            raise ValueError("plugin_id is required for this action")
        return self.plugin_id
