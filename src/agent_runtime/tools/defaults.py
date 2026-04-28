from __future__ import annotations

from agent_runtime.tools.backup_tools import RestoreBackupTool
from agent_runtime.tools.command_tools import RunCommandTool, RunTestsTool
from agent_runtime.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from agent_runtime.tools.patch_tools import ApplyPatchTool, DiffWorkspaceTool
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.search_tools import FindFilesTool, SearchTextTool


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
    registry.register(RunCommandTool())
    registry.register(RunTestsTool())
    return registry
