from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.workspace_registry import WorkspaceRegistry
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class WorkspacesResult:
    ok: bool
    workspace: str | None = None
    initialized: bool = False
    registry: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"ok": self.ok}
        if self.workspace is not None:
            payload["workspace"] = self.workspace
        if self.initialized:
            payload["initialized"] = self.initialized
        if self.registry is not None:
            payload["registry"] = self.registry
        if self.error:
            payload["error"] = self.error
        return payload

    def to_text(self) -> str:
        if not self.ok:
            return self.error or "workspace command failed"
        if self.workspace:
            return f"Workspace registered: {self.workspace}"
        recent = (self.registry or {}).get("recent_workspaces") or []
        lines = ["Recent workspaces:"]
        if not recent:
            lines.append("  (none)")
        else:
            for item in recent[:10]:
                name = item.get("name") or item.get("workspace_root") or "unknown"
                root = item.get("workspace_root") or "unknown"
                lines.append(f"  - {name}: {root}")
        current = (self.registry or {}).get("current_workspace_root")
        if current:
            lines.append(f"Current: {current}")
        return "\n".join(lines)


class WorkspacesCommand:
    def __init__(self, *, global_config_dir: Path | None = None) -> None:
        self.validator = SchemaValidator(schema_dir())
        self.global_config_dir = global_config_dir

    def list_registry(self) -> WorkspacesResult:
        registry = WorkspaceRegistry(self.global_config_dir, self.validator).read()
        return WorkspacesResult(ok=True, registry=registry)

    def register(
        self,
        workspace_root: Path,
        *,
        init_if_needed: bool = True,
    ) -> WorkspacesResult:
        root = workspace_root.expanduser().resolve()
        if not root.exists():
            return WorkspacesResult(ok=False, error=f"Workspace path does not exist: {root}")
        if not root.is_dir():
            return WorkspacesResult(ok=False, error=f"Workspace path is not a directory: {root}")

        initialized = False
        project_json = root / ".asteria" / "project.json"
        if init_if_needed and not project_json.exists():
            InitCommand(root, global_config_dir=self.global_config_dir).run()
            initialized = True
        else:
            WorkspaceRegistry(self.global_config_dir, self.validator).record_workspace(
                workspace_root=root,
            )

        registry = WorkspaceRegistry(self.global_config_dir, self.validator).read()
        return WorkspacesResult(
            ok=True,
            workspace=str(root),
            initialized=initialized,
            registry=registry,
        )
