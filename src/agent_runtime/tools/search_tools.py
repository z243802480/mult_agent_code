from __future__ import annotations

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.path_guard import PathGuard, PathPolicyError
from agent_runtime.tools.base import ToolResult


class SearchTextTool:
    name = "search_text"

    def __init__(self, max_results: int = 100, max_file_bytes: int = 200_000) -> None:
        self.max_results = max_results
        self.max_file_bytes = max_file_bytes

    def run(
        self,
        context: RuntimeContext,
        pattern: str,
        path: str = ".",
        case_sensitive: bool = False,
    ) -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        root = guard.resolve_for_read(path)
        if not root.exists():
            return ToolResult(ok=False, summary=f"Path not found: {path}", error="path_not_found")

        needle = pattern if case_sensitive else pattern.lower()
        results: list[dict[str, object]] = []
        scanned = 0
        files = [root] if root.is_file() else root.rglob("*")
        for candidate in files:
            if len(results) >= self.max_results:
                break
            if not candidate.is_file():
                continue
            try:
                rel = candidate.relative_to(context.root).as_posix()
                guard.resolve_for_read(rel)
            except (ValueError, PathPolicyError):
                continue
            if candidate.stat().st_size > self.max_file_bytes:
                continue
            scanned += 1
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    results.append(
                        {
                            "path": rel,
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(results) >= self.max_results:
                        break

        return ToolResult(
            ok=True,
            summary=f"Found {len(results)} matches for {pattern!r}",
            data={"matches": results, "scanned_files": scanned},
        )


class FindFilesTool:
    name = "find_files"

    def __init__(self, max_results: int = 500) -> None:
        self.max_results = max_results

    def run(self, context: RuntimeContext, glob: str, path: str = ".") -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        root = guard.resolve_for_read(path)
        if not root.exists() or not root.is_dir():
            return ToolResult(ok=False, summary=f"Directory not found: {path}", error="directory_not_found")
        results: list[dict[str, str]] = []
        for candidate in root.rglob(glob):
            if len(results) >= self.max_results:
                break
            rel = candidate.relative_to(context.root).as_posix()
            try:
                guard.resolve_for_read(rel)
            except PathPolicyError:
                continue
            results.append({"path": rel, "type": "dir" if candidate.is_dir() else "file"})
        return ToolResult(
            ok=True,
            summary=f"Found {len(results)} paths for glob {glob!r}",
            data={"paths": results},
        )
