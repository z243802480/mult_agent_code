import json
from pathlib import Path

from asteria_runtime.core.plugin_manifest import PluginManifestLoader
from asteria_runtime.core.policy_config import merge_policy_defaults
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_plugin_manifest_loader_keeps_plugins_disabled_by_default(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".asteria"
    plugin_dir = agent_dir / "plugins"
    plugin_dir.mkdir(parents=True)
    _write_manifest(plugin_dir / "audit.plugin.json")
    policy = merge_policy_defaults({})

    manifests = PluginManifestLoader(SchemaValidator(Path.cwd() / "schemas")).load(
        agent_dir,
        policy,
    )

    assert len(manifests) == 1
    assert manifests[0].plugin_id == "example.audit"
    assert manifests[0].status == "disabled"
    assert manifests[0].executable is False


def test_plugin_manifest_loader_blocks_unknown_hook_subscription(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".asteria"
    plugin_dir = agent_dir / "plugins"
    plugin_dir.mkdir(parents=True)
    _write_manifest(plugin_dir / "audit.plugin.json", hook_subscriptions=["unknown_hook"])
    policy = merge_policy_defaults({"hooks": {"plugins_enabled": True}})

    manifests = PluginManifestLoader(SchemaValidator(Path.cwd() / "schemas")).load(
        agent_dir,
        policy,
    )

    assert manifests[0].status == "blocked"
    assert "unknown_hook" in manifests[0].reason


def _write_manifest(path: Path, hook_subscriptions: list[str] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "plugin_id": "example.audit",
                "name": "Example Audit Plugin",
                "version": "0.1.0",
                "enabled": True,
                "entrypoint": "plugins/example_audit.py",
                "hook_subscriptions": hook_subscriptions or ["after_tool_call"],
                "permissions": {
                    "network": False,
                    "shell": False,
                    "write_workspace": False,
                    "read_secrets": False,
                },
                "capabilities": ["audit-log"],
                "description": "Records audit metadata.",
            }
        ),
        encoding="utf-8",
    )
