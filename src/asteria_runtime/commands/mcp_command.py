"""`asteria mcp` — inspect the curated MCP server catalog and opt servers in/out.

Out of the box the workspace ships with ``mcp.servers=[]`` (see templates/policies.default.json),
so a fresh run reaches no MCP server and stays offline/local-first. This command surfaces a curated
catalog of well-known reference servers (templates/mcp_catalog.json) with honest labels — which reach
the network, which runtime they need, and where they overlap native tools — and lets the operator
enable/disable them by writing into the workspace ``policies.json`` ``mcp.servers`` list. The live
execute path reads that same list (``execute_command._wire_mcp_adapter`` →
``mcp_adapter_config_from_policy``), so enabling here is what actually wires a server into the model's
tool surface on the next run.

Read-only for ``list``; ``enable``/``disable`` edit only the ``mcp.servers`` list in policies.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.resources import template_path
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def _catalog_document() -> dict[str, Any]:
    return json.loads(template_path("mcp_catalog.json").read_text(encoding="utf-8"))


def load_mcp_catalog() -> list[dict[str, Any]]:
    servers = _catalog_document().get("servers")
    return [s for s in servers if isinstance(s, dict)] if isinstance(servers, list) else []


@dataclass(frozen=True)
class McpResult:
    action: str
    root: Path
    servers: list[dict[str, Any]]
    enabled_names: list[str]
    runtime_note: str
    summary: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "action": self.action,
            "root": str(self.root),
            "ok": self.ok,
            "summary": self.summary,
            "enabled_names": self.enabled_names,
            "runtime_note": self.runtime_note,
            "servers": self.servers,
            "warnings": self.warnings,
        }

    def to_text(self) -> str:
        lines = [
            f"MCP action: {self.action}",
            f"Summary: {self.summary}",
        ]
        if self.runtime_note:
            lines.append(f"Note: {self.runtime_note}")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.append("Catalog:")
        for server in self.servers:
            mark = "on " if server.get("enabled") else "off"
            net = "network" if server.get("reaches_network") else "local"
            rec = " (recommended)" if server.get("recommended") else ""
            lines.append(f"- [{mark}] {server['name']} <{net}>{rec}: {server.get('description', '')}")
            runtime = server.get("requires_runtime")
            if runtime:
                lines.append(f"    runtime: {runtime}")
            notes = server.get("notes")
            if notes:
                lines.append(f"    notes: {notes}")
        return "\n".join(lines)


class McpCommand:
    def __init__(
        self,
        root: Path,
        action: str = "list",
        name: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.action = action
        self.name = name
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> McpResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
        if self.action in {"enable", "disable"}:
            self._set_enabled(agent_dir, self._require_name(), self.action == "enable")
        elif self.action != "list":
            raise ValueError(f"Unsupported mcp action: {self.action}")
        return self._view(agent_dir)

    def to_json(self, result: McpResult) -> str:
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    # -- internals ---------------------------------------------------------

    def _policy_path(self, agent_dir: Path) -> Path:
        return agent_dir / "policies.json"

    def _read_policy(self, agent_dir: Path) -> dict[str, Any]:
        return self.store.read(self._policy_path(agent_dir), "policy_config")

    def _enabled_servers(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        mcp = policy.get("mcp")
        servers = mcp.get("servers") if isinstance(mcp, dict) else None
        return [s for s in servers if isinstance(s, dict)] if isinstance(servers, list) else []

    def _set_enabled(self, agent_dir: Path, name: str, enabled: bool) -> None:
        catalog = {entry["name"]: entry for entry in load_mcp_catalog()}
        policy = self._read_policy(agent_dir)
        mcp = policy.get("mcp")
        if not isinstance(mcp, dict):
            mcp = {"session_call_timeout_seconds": 60, "retry_attempts": 1, "servers": []}
        servers = [s for s in (mcp.get("servers") or []) if isinstance(s, dict)]
        # Remove any existing entry with this name (idempotent enable, clean disable).
        servers = [s for s in servers if s.get("name") != name]
        if enabled:
            entry = catalog.get(name)
            if entry is None:
                raise ValueError(
                    f"Unknown MCP server '{name}'. Run `asteria mcp list` to see the catalog."
                )
            servers.append(self._server_config(entry))
        mcp["servers"] = servers
        policy["mcp"] = mcp
        self.store.write(self._policy_path(agent_dir), policy, "policy_config")

    def _server_config(self, entry: dict[str, Any]) -> dict[str, Any]:
        # Persist only the fields the runtime adapter consumes (mcp_server_config_from_dict);
        # the catalog's label fields (notes/reaches_network/...) are guidance, not runtime config.
        config: dict[str, Any] = {
            "name": entry["name"],
            "command": [str(part) for part in entry.get("command") or []],
        }
        if entry.get("cwd"):
            config["cwd"] = str(entry["cwd"])
        if isinstance(entry.get("env"), dict) and entry["env"]:
            config["env"] = {str(k): str(v) for k, v in entry["env"].items()}
        if entry.get("framing"):
            config["framing"] = str(entry["framing"])
        return config

    def _view(self, agent_dir: Path) -> McpResult:
        policy = self._read_policy(agent_dir)
        enabled_servers = self._enabled_servers(policy)
        enabled_names = {str(s.get("name")) for s in enabled_servers if s.get("name")}
        catalog = load_mcp_catalog()
        catalog_names = {entry["name"] for entry in catalog}
        rows: list[dict[str, Any]] = [
            {**entry, "enabled": entry["name"] in enabled_names} for entry in catalog
        ]
        # Surface workspace-defined servers that are not part of the shipped catalog.
        for server in enabled_servers:
            server_name = str(server.get("name") or "")
            if server_name and server_name not in catalog_names:
                rows.append(
                    {
                        "name": server_name,
                        "command": server.get("command"),
                        "description": "(workspace-defined server, not from the shipped catalog)",
                        "reaches_network": None,
                        "requires_runtime": None,
                        "recommended": False,
                        "notes": "Defined directly in policies.json mcp.servers.",
                        "enabled": True,
                    }
                )
        warnings = [
            f"'{row['name']}' is enabled and reaches the network."
            for row in rows
            if row.get("enabled") and row.get("reaches_network")
        ]
        summary = f"{len(enabled_names)} MCP server(s) enabled; {len(catalog)} in catalog."
        return McpResult(
            action=self.action,
            root=self.root,
            servers=rows,
            enabled_names=sorted(enabled_names),
            runtime_note=str(_catalog_document().get("runtime_note") or ""),
            summary=summary,
            warnings=warnings,
        )

    def _require_name(self) -> str:
        if not self.name:
            raise ValueError("--name is required for enable/disable")
        return self.name
