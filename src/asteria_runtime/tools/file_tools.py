from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.file_backup import FileBackupStore
from asteria_runtime.tools.base import ToolResult


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
        existed_before = resolved.exists()
        if existed_before and not overwrite:
            return ToolResult(
                ok=False,
                summary=f"File exists and overwrite is false: {path}",
                error="file_exists",
            )
        backup = FileBackupStore(context).backup_paths([resolved], "write_file")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        byte_count = len(content.encode(encoding))
        resolved.write_bytes(content.encode(encoding))
        self._clear_python_bytecode(resolved)
        # Tell the model explicitly whether this CREATED a new file or OVERWROTE an existing one, and
        # that the file now exists. A weak model that only saw "Wrote file: X" could not tell the two
        # apart and would blindly re-issue write_file for a path it had already produced (a same-path
        # rewrite then hard-fails on overwrite=False). Surfacing created/modified + "now exists" here
        # is the cheapest signal that stops the redundant re-write loop. (ADR-0024 §5 #1)
        operation = "modified" if existed_before else "created"
        verb = "Overwrote existing" if existed_before else "Created new"
        return ToolResult(
            ok=True,
            summary=f"{verb} file: {path} ({byte_count} bytes) — it now exists at {path}",
            data={
                "path": resolved.relative_to(context.root).as_posix(),
                "bytes": byte_count,
                "backup_id": backup["backup_id"],
                "operation": operation,
                "existed_before": existed_before,
            },
        )

    def _clear_python_bytecode(self, path: Path) -> None:
        if path.suffix != ".py":
            return
        cache_dir = path.parent / "__pycache__"
        if not cache_dir.exists():
            return
        for cached in cache_dir.glob(f"{path.stem}.*.pyc"):
            cached.unlink(missing_ok=True)


class ListFilesTool:
    name = "list_files"

    def __init__(self, max_entries: int = 500) -> None:
        self.max_entries = max_entries

    def run(self, context: RuntimeContext, path: str = ".") -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        resolved = guard.resolve_for_read(path)
        if not resolved.exists():
            return ToolResult(
                ok=True,
                summary=f"Listed 0 entries under {path} (path does not exist yet)",
                data={"entries": [], "path_exists": False},
                warnings=["path_not_found"],
            )
        if not resolved.is_dir():
            return ToolResult(ok=False, summary=f"Not a directory: {path}", error="not_a_directory")

        entries: list[dict[str, str]] = []
        warnings: list[str] = []
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
            data={"entries": entries, "path_exists": True},
            warnings=warnings,
        )
