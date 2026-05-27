from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.workspace_envelope import workspace_id
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class WorkspaceRegistry:
    """User-level recent/current workspace index.

    This index stores only product navigation pointers. Runtime evidence,
    sessions, runs, and artifacts remain workspace-local under `.asteria/`.
    """

    global_dir: Path | None = None
    validator: SchemaValidator | None = None

    @property
    def root(self) -> Path:
        if self.global_dir is not None:
            return self.global_dir
        configured = os.environ.get("ASTERIA_HOME")
        if configured:
            return Path(configured).expanduser().resolve()
        return Path.home() / ".asteria"

    @property
    def path(self) -> Path:
        return self.root / "workspaces.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        return JsonStore(self.validator).read(self.path, "workspace_registry")

    def record_workspace(
        self,
        *,
        workspace_root: Path,
        name: str | None = None,
        output_root: Path | None = None,
        artifact_root: Path | None = None,
        set_current: bool = True,
    ) -> dict[str, Any]:
        root = workspace_root.resolve()
        output = (output_root or root).resolve()
        artifacts = (artifact_root or root / ".asteria" / "artifacts").resolve()
        registry = self.read()
        workspace = {
            "workspace_id": workspace_id(root),
            "name": name or root.name,
            "workspace_root": str(root),
            "output_root": str(output),
            "artifact_root": str(artifacts),
            "last_opened_at": now_iso(),
        }
        recent = [
            item
            for item in registry.get("recent_workspaces", [])
            if item.get("workspace_id") != workspace["workspace_id"]
        ]
        recent.insert(0, workspace)
        registry.update(
            {
                "schema_version": SCHEMA_VERSION,
                "current_workspace_id": workspace["workspace_id"]
                if set_current
                else registry.get("current_workspace_id"),
                "current_workspace_root": str(root)
                if set_current
                else registry.get("current_workspace_root"),
                "recent_workspaces": recent[:20],
                "updated_at": now_iso(),
            }
        )
        JsonStore(self.validator).write(self.path, registry, "workspace_registry")
        return registry

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "current_workspace_id": None,
            "current_workspace_root": None,
            "recent_workspaces": [],
            "updated_at": now_iso(),
        }
