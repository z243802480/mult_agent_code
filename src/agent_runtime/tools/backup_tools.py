from __future__ import annotations

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.storage.file_backup import FileBackupStore
from agent_runtime.tools.base import ToolResult


class RestoreBackupTool:
    name = "restore_backup"

    def run(
        self,
        context: RuntimeContext,
        backup_id: str,
        delete_created_files: bool = False,
    ) -> ToolResult:
        allow_delete = bool(
            context.policy.get("permissions", {}).get("allow_restore_delete_created_files", False)
        )
        if delete_created_files and not allow_delete:
            return ToolResult(
                ok=False,
                summary="Deleting created files during restore is not allowed by policy",
                error="restore_delete_created_files_denied",
                status="denied",
            )

        restored = FileBackupStore(context).restore(
            backup_id,
            delete_created_files=delete_created_files,
        )
        return ToolResult(
            ok=True,
            summary=f"Restored backup: {backup_id}",
            data=restored,
            warnings=restored["warnings"],
        )
