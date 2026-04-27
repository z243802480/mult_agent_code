from __future__ import annotations

import difflib
from dataclasses import dataclass

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.path_guard import PathGuard
from agent_runtime.tools.base import ToolResult


class PatchApplyError(ValueError):
    pass


@dataclass(frozen=True)
class FilePatch:
    path: str
    old_lines: list[str]
    new_lines: list[str]


class ApplyPatchTool:
    name = "apply_patch"

    def run(self, context: RuntimeContext, patch: str) -> ToolResult:
        patches = parse_unified_diff(patch)
        if not patches:
            return ToolResult(ok=False, summary="No file patches found", error="empty_patch")
        guard = PathGuard(context.root, context.policy["protected_paths"])
        changed = []
        for file_patch in patches:
            resolved = guard.resolve_for_write(file_patch.path)
            current = resolved.read_text(encoding="utf-8").splitlines(keepends=True) if resolved.exists() else []
            if current != file_patch.old_lines:
                return ToolResult(
                    ok=False,
                    summary=f"Patch context mismatch for {file_patch.path}",
                    error="patch_context_mismatch",
                    data={"path": file_patch.path},
                )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text("".join(file_patch.new_lines), encoding="utf-8")
            changed.append(file_patch.path)
        return ToolResult(
            ok=True,
            summary=f"Applied patch to {len(changed)} file(s)",
            data={"changed_files": changed},
        )


class DiffWorkspaceTool:
    name = "diff_workspace"

    def run(self, context: RuntimeContext, path: str, original: str) -> ToolResult:
        guard = PathGuard(context.root, context.policy["protected_paths"])
        resolved = guard.resolve_for_read(path)
        if not resolved.exists() or not resolved.is_file():
            return ToolResult(ok=False, summary=f"File not found: {path}", error="file_not_found")
        current = resolved.read_text(encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return ToolResult(
            ok=True,
            summary=f"Generated diff for {path}",
            data={"path": path, "diff": diff},
        )


def parse_unified_diff(patch: str) -> list[FilePatch]:
    lines = patch.splitlines(keepends=True)
    patches: list[FilePatch] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_header = lines[index].strip()
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchApplyError("Unified diff missing +++ header")
        new_header = lines[index].strip()
        index += 1
        path = _path_from_headers(old_header, new_header)
        old_lines: list[str] = []
        new_lines: list[str] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            line = lines[index]
            index += 1
            if line.startswith("@@"):
                continue
            if line.startswith(" "):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif line.startswith("-"):
                old_lines.append(line[1:])
            elif line.startswith("+"):
                new_lines.append(line[1:])
            elif line.startswith("\\"):
                continue
            elif line.strip() == "":
                # Empty context line from malformed generators is treated as context.
                old_lines.append(line)
                new_lines.append(line)
        patches.append(FilePatch(path=path, old_lines=old_lines, new_lines=new_lines))
    return patches


def _path_from_headers(old_header: str, new_header: str) -> str:
    candidate = new_header[4:] if not new_header.endswith("/dev/null") else old_header[4:]
    if candidate.startswith("b/") or candidate.startswith("a/"):
        candidate = candidate[2:]
    if candidate in {"/dev/null", "dev/null"}:
        raise PatchApplyError("Creating or deleting files via unified diff is not supported yet")
    return candidate
