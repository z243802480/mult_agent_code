from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.plugin_manifest import PluginManifestLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.schema_validator import SchemaValidator


def plugin_control_summary(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    root = root.resolve()
    agent_dir = root / ".asteria"
    if not agent_dir.exists():
        return {
            "initialized": False,
            "ok": True,
            "plugin_dir": str(agent_dir / "plugins"),
            "hook_policy": {},
            "plugins": [],
            "status_counts": {},
            "warnings": [],
            "summary": "Workspace is not initialized; plugin control surface is inactive.",
        }
    policy = load_policy_config(agent_dir, validator)
    hook_policy = _hook_policy(policy)
    loaded = PluginManifestLoader(validator).load(agent_dir, policy)
    plugins = [
        {
            "plugin_id": item.plugin_id,
            "name": item.manifest.get("name"),
            "version": item.manifest.get("version"),
            "status": item.status,
            "reason": item.reason,
            "manifest_enabled": bool(item.manifest.get("enabled")),
            "hook_subscriptions": list(item.manifest.get("hook_subscriptions") or []),
            "permissions": item.manifest.get("permissions") or {},
            "capabilities": list(item.manifest.get("capabilities") or []),
            "path": str(item.path),
            "executable": item.executable,
        }
        for item in loaded
    ]
    status_counts = _status_counts(plugins)
    warnings = _warnings(hook_policy, plugins)
    return {
        "initialized": True,
        "ok": status_counts.get("blocked", 0) == 0,
        "plugin_dir": str(agent_dir / "plugins"),
        "hook_policy": hook_policy,
        "plugins": plugins,
        "status_counts": status_counts,
        "warnings": warnings,
        "summary": (
            f"{len(plugins)} manifest(s), "
            f"enabled={status_counts.get('enabled', 0)}, "
            f"disabled={status_counts.get('disabled', 0)}, "
            f"blocked={status_counts.get('blocked', 0)}; "
            f"plugin execution={'on' if hook_policy['plugins_enabled'] else 'off'}."
        ),
    }


def _hook_policy(policy: dict[str, Any]) -> dict[str, Any]:
    raw_hooks = policy.get("hooks")
    hooks: dict[str, Any] = raw_hooks if isinstance(raw_hooks, dict) else {}
    return {
        "enabled": bool(hooks.get("enabled", True)),
        "plugins_enabled": bool(hooks.get("plugins_enabled", False)),
        "allowed_hook_names": list(hooks.get("allowed_hook_names") or []),
        "redacted_data_keys": list(hooks.get("redacted_data_keys") or []),
        "handler_timeout_ms": int(hooks.get("handler_timeout_ms") or 0),
    }


def _status_counts(plugins: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for plugin in plugins:
        status = str(plugin.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _warnings(hook_policy: dict[str, Any], plugins: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if not hook_policy["enabled"]:
        warnings.append("hooks.enabled=false; runtime hook events will not be recorded.")
    if not hook_policy["plugins_enabled"] and any(
        bool(plugin.get("manifest_enabled")) for plugin in plugins
    ):
        warnings.append(
            "hooks.plugins_enabled=false; enabled manifests are metadata-only and cannot run."
        )
    blocked = [str(plugin["plugin_id"]) for plugin in plugins if plugin["status"] == "blocked"]
    if blocked:
        warnings.append("Blocked plugin manifests: " + ", ".join(blocked))
    return warnings
