import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plugins_command import PluginsCommand


def test_plugins_command_lists_manifest_as_metadata_only_by_default(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_manifest(tmp_path / ".asteria" / "plugins" / "audit.plugin.json", enabled=True)

    result = PluginsCommand(tmp_path).run()

    assert result.ok is True
    assert result.hook_policy["plugins_enabled"] is False
    assert result.plugins[0]["plugin_id"] == "example.audit"
    assert result.plugins[0]["status"] == "disabled"
    assert "metadata-only" in " ".join(result.warnings)


def test_plugins_command_enable_and_disable_updates_manifest(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    manifest_path = tmp_path / ".asteria" / "plugins" / "audit.plugin.json"
    _write_manifest(manifest_path, enabled=False)

    enabled = PluginsCommand(tmp_path, action="enable", plugin_id="example.audit").run()
    assert enabled.plugins[0]["manifest_enabled"] is True
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["enabled"] is True

    disabled = PluginsCommand(tmp_path, action="disable", plugin_id="example.audit").run()
    assert disabled.plugins[0]["manifest_enabled"] is False
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["enabled"] is False


def test_plugins_command_doctor_marks_disallowed_hook_as_not_ok(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_manifest(
        tmp_path / ".asteria" / "plugins" / "audit.plugin.json",
        hook_subscriptions=["unknown_hook"],
    )

    result = PluginsCommand(tmp_path, action="doctor").run()

    assert result.ok is False
    assert result.plugins[0]["status"] == "blocked"
    assert "unknown_hook" in result.plugins[0]["reason"]


def _write_manifest(
    path: Path,
    *,
    enabled: bool = True,
    hook_subscriptions: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "plugin_id": "example.audit",
                "name": "Example Audit Plugin",
                "version": "0.1.0",
                "enabled": enabled,
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
