from __future__ import annotations

from asteria_runtime.tools.backup_tools import RestoreBackupTool
from asteria_runtime.tools.command_tools import RunCommandTool, RunTestsTool
from asteria_runtime.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from asteria_runtime.tools.memory_tools import RecallMemoryTool, RememberTool
from asteria_runtime.tools.patch_tools import ApplyPatchTool, DiffWorkspaceTool
from asteria_runtime.tools.registry import ToolRegistry
from asteria_runtime.tools.search_tools import FindFilesTool, SearchTextTool
from asteria_runtime.tools.todo_tools import TodoReadTool, TodoWriteTool


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ListFilesTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(FindFilesTool())
    registry.register(SearchTextTool())
    registry.register(ApplyPatchTool())
    registry.register(DiffWorkspaceTool())
    registry.register(RestoreBackupTool())
    registry.register(TodoReadTool())
    registry.register(TodoWriteTool())
    registry.register(RememberTool())
    registry.register(RecallMemoryTool())
    registry.register(RunCommandTool())
    registry.register(RunTestsTool())
    return registry
