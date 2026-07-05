"""`asteria mcp` catalog: list shows honest labels; enable/disable edit policy mcp.servers."""
from pathlib import Path

import pytest

from asteria_runtime.commands.mcp_command import McpCommand, load_mcp_catalog
from asteria_runtime.core.mcp_adapter import mcp_adapter_config_from_policy
from asteria_runtime.core.policy_config import merge_policy_defaults
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def _workspace(tmp_path: Path) -> Path:
    agent_dir = tmp_path / ".asteria"
    agent_dir.mkdir(parents=True)
    validator = SchemaValidator(Path.cwd() / "schemas")
    JsonStore(validator).write(agent_dir / "policies.json", merge_policy_defaults({}), "policy_config")
    return tmp_path


def _policy(tmp_path: Path) -> dict:
    validator = SchemaValidator(Path.cwd() / "schemas")
    return JsonStore(validator).read(tmp_path / ".asteria" / "policies.json", "policy_config")


def test_catalog_is_curated_and_honest() -> None:
    catalog = load_mcp_catalog()
    names = {entry["name"] for entry in catalog}
    # A small curated set, not the whole ecosystem.
    assert {"git", "fetch"} <= names
    for entry in catalog:
        assert entry["description"].strip()
        assert isinstance(entry["command"], list) and entry["command"]
        assert "reaches_network" in entry  # network posture is stated for every server
        assert entry["notes"].strip()
    # fetch is the network server and is honestly flagged; git is local.
    by_name = {e["name"]: e for e in catalog}
    assert by_name["fetch"]["reaches_network"] is True
    assert by_name["git"]["reaches_network"] is False


def test_list_shows_disabled_by_default(tmp_path: Path) -> None:
    result = McpCommand(_workspace(tmp_path), "list").run()
    assert result.enabled_names == []
    assert result.warnings == []
    assert {s["name"] for s in result.servers} == {e["name"] for e in load_mcp_catalog()}
    assert all(s["enabled"] is False for s in result.servers)
    assert result.runtime_note  # the offline/first-fetch caveat is surfaced


def test_enable_writes_server_into_policy_and_is_runtime_parseable(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    McpCommand(root, "enable", name="git").run()
    policy = _policy(root)
    servers = policy["mcp"]["servers"]
    assert [s["name"] for s in servers] == ["git"]
    # The persisted entry is a valid runtime server config, not the catalog label blob.
    assert "notes" not in servers[0] and "reaches_network" not in servers[0]
    config = mcp_adapter_config_from_policy(policy, root=root)
    assert [s.name for s in config.servers] == ["git"]
    # list now reflects it as enabled
    result = McpCommand(root, "list").run()
    assert result.enabled_names == ["git"]


def test_enable_is_idempotent_no_duplicates(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    McpCommand(root, "enable", name="git").run()
    McpCommand(root, "enable", name="git").run()
    assert [s["name"] for s in _policy(root)["mcp"]["servers"]] == ["git"]


def test_enabling_network_server_raises_warning(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    McpCommand(root, "enable", name="fetch").run()
    result = McpCommand(root, "list").run()
    assert result.enabled_names == ["fetch"]
    assert any("network" in w for w in result.warnings)


def test_disable_removes_server(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    McpCommand(root, "enable", name="git").run()
    McpCommand(root, "disable", name="git").run()
    assert _policy(root)["mcp"]["servers"] == []
    assert McpCommand(root, "list").run().enabled_names == []


def test_enable_unknown_name_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(ValueError, match="Unknown MCP server"):
        McpCommand(root, "enable", name="does-not-exist").run()


def test_enable_requires_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name is required"):
        McpCommand(_workspace(tmp_path), "enable").run()


def test_uninitialized_workspace_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        McpCommand(tmp_path, "list").run()


def test_workspace_defined_server_surfaces_in_list(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    path = root / ".asteria" / "policies.json"
    policy = store.read(path, "policy_config")
    policy["mcp"]["servers"] = [{"name": "internal-docs", "command": ["python", "-m", "docs_server"]}]
    store.write(path, policy, "policy_config")
    result = McpCommand(root, "list").run()
    row = next(s for s in result.servers if s["name"] == "internal-docs")
    assert row["enabled"] is True
    assert "workspace-defined" in row["description"]
