from __future__ import annotations

from pathlib import Path

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.path_guard import PathGuard
from agent_runtime.tools.base import ToolResult


class ReadFileTool:
    name = "read_file"

    def __init__(self, max_bytes: int = 200_000) -> None:
        self.max_bytes = max_bytes

    def run(self, context: RuntimeContext, path: str, encoding: str = "utf-8") -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        resolved = guard.resolve_for_read(path)
        if not resolved.exists():
            return ToolResult(ok=False, summary=f"File not found: {path}", error="file_not_found")
        if not resolved.is_file():
            return ToolResult(ok=False, summary=f"Not a file: {path}", error="not_a_file")
        size = resolved.stat().st_size
        if size > self.max_bytes:
            return ToolResult(
                ok=False,
                summary=f"File too large: {path} ({size} bytes)",
                error="file_too_large",
                data={"size": size, "max_bytes": self.max_bytes},
            )
        content = resolved.read_text(encoding=encoding)
        return ToolResult(
            ok=True,
            summary=f"Read file: {path}",
            data={
                "path": resolved.relative_to(context.root).as_posix(),
                "content": content,
                "size": size,
            },
        )


class WriteFileTool:
    name = "write_file"

    def run(
        self,
        context: RuntimeContext,
        path: str,
        content: str,
        overwrite: bool = False,
        encoding: str = "utf-8",
    ) -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        resolved = guard.resolve_for_write(path)
        if resolved.exists() and not overwrite:
            return ToolResult(
                ok=False,
                summary=f"File exists and overwrite is false: {path}",
                error="file_exists",
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return ToolResult(
            ok=True,
            summary=f"Wrote file: {path}",
            data={"path": resolved.relative_to(context.root).as_posix(), "bytes": len(content.encode(encoding))},
        )


class ListFilesTool:
    name = "list_files"

    def __init__(self, max_entries: int = 500) -> None:
        self.max_entries = max_entries

    def run(self, context: RuntimeContext, path: str = ".") -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        resolved = guard.resolve_for_read(path)
        if not resolved.exists():
            return ToolResult(ok=False, summary=f"Path not found: {path}", error="path_not_found")
        if not resolved.is_dir():
            return ToolResult(ok=False, summary=f"Not a directory: {path}", error="not_a_directory")

        entries = []
        warnings = []
        for child in sorted(resolved.iterdir(), key=lambda item: item.name.lower()):
            if len(entries) >= self.max_entries:
                warnings.append(f"Entry limit reached: {self.max_entries}")
                break
            rel = child.relative_to(context.root).as_posix()
            try:
                guard.resolve_for_read(rel)
            except PermissionError:
                continue
            entries.append({"path": rel, "type": "dir" if child.is_dir() else "file"})
        return ToolResult(
            ok=True,
            summary=f"Listed {len(entries)} entries under {path}",
            data={"entries": entries},
            warnings=warnings,
        )
