from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.file_backup import FileBackupStore
from asteria_runtime.tools.base import ToolResult


class PatchApplyError(ValueError):
    pass


@dataclass(frozen=True)
class FilePatch:
    path: str
    hunks: list[tuple[list[str], list[str]]]
    mode: str = "modify"  # "modify" | "create" (--- /dev/null) | "delete" (+++ /dev/null)


class ApplyPatchTool:
    name = "apply_patch"

    def run(self, context: RuntimeContext, patch: str | None = None, diff: str | None = None) -> ToolResult:
        patch_text = patch if patch is not None else diff
        if patch_text is None:
            return ToolResult(ok=False, summary="Patch text is required", error="missing_patch")
        patches = parse_unified_diff(patch_text)
        if not patches:
            return ToolResult(ok=False, summary="No file patches found", error="empty_patch")
        guard = PathGuard(context.root, context.policy["protected_paths"])
        # (path, resolved, patched_lines_or_None, mode); patched is None for deletions.
        planned: list[tuple[str, Path, list[str] | None, str]] = []
        for file_patch in patches:
            resolved = guard.resolve_for_write(file_patch.path)
            if file_patch.mode == "delete":
                if not resolved.exists():
                    return ToolResult(
                        ok=False,
                        summary=f"Cannot delete missing file: {file_patch.path}",
                        error="delete_missing_file",
                        data={"path": file_patch.path},
                    )
                planned.append((file_patch.path, resolved, None, "delete"))
                continue
            # A `--- /dev/null` create applies against an empty file even if a stale one
            # exists; a modify reads current content (empty when the file is absent).
            current = (
                []
                if file_patch.mode == "create"
                else resolved.read_text(encoding="utf-8").splitlines(keepends=True)
                if resolved.exists()
                else []
            )
            patched = apply_file_patch(current, file_patch.hunks)
            if patched is None:
                return ToolResult(
                    ok=False,
                    summary=f"Patch context mismatch for {file_patch.path}",
                    error="patch_context_mismatch",
                    data={"path": file_patch.path},
                )
            planned.append((file_patch.path, resolved, patched, file_patch.mode))

        backup = FileBackupStore(context).backup_paths(
            [resolved for _, resolved, _, _ in planned],
            "apply_patch",
        )
        changed: list[str] = []
        deleted: list[str] = []
        for path, resolved, patched, mode in planned:
            if mode == "delete":
                resolved.unlink(missing_ok=True)
                _clear_python_bytecode(resolved)
                deleted.append(path)
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text("".join(patched or []), encoding="utf-8")
            _clear_python_bytecode(resolved)
            changed.append(path)
        parts: list[str] = []
        if changed:
            parts.append(f"{len(changed)} file(s) changed")
        if deleted:
            parts.append(f"{len(deleted)} file(s) deleted")
        return ToolResult(
            ok=True,
            summary="Applied patch: " + ", ".join(parts) if parts else "Applied patch (no-op)",
            data={
                "changed_files": changed,
                "deleted_files": deleted,
                "backup_id": backup["backup_id"],
            },
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
        path, mode = _path_from_headers(old_header, new_header)
        hunks: list[tuple[list[str], list[str]]] = []
        old_lines: list[str] = []
        new_lines: list[str] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            line = lines[index]
            index += 1
            if line.startswith("@@"):
                if old_lines or new_lines:
                    hunks.append((old_lines, new_lines))
                    old_lines = []
                    new_lines = []
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
        if old_lines or new_lines:
            hunks.append((old_lines, new_lines))
        patches.append(FilePatch(path=path, hunks=hunks, mode=mode))
    return patches


def apply_file_patch(current: list[str], hunks: list[tuple[list[str], list[str]]]) -> list[str] | None:
    result: list[str] = []
    search_from = 0
    for old_lines, new_lines in hunks:
        match_at = _find_hunk(current, old_lines, search_from)
        if match_at is None:
            return None
        result.extend(current[search_from:match_at])
        result.extend(new_lines)
        search_from = match_at + len(old_lines)
    result.extend(current[search_from:])
    return result


def _find_hunk(current: list[str], old_lines: list[str], start: int) -> int | None:
    if not old_lines:
        return start
    last_start = len(current) - len(old_lines)
    for index in range(start, last_start + 1):
        if current[index : index + len(old_lines)] == old_lines:
            return index
    return None


def _path_from_headers(old_header: str, new_header: str) -> tuple[str, str]:
    """Return (target_path, mode) where mode is modify | create | delete.

    A `--- /dev/null` header marks a new file (create); a `+++ /dev/null` header marks a
    deletion. Otherwise the `+++ b/<path>` side names the target of an in-place modify.
    """
    old_target = _strip_ab_prefix(old_header[4:])
    new_target = _strip_ab_prefix(new_header[4:])
    old_is_null = old_target in {"/dev/null", "dev/null"}
    new_is_null = new_target in {"/dev/null", "dev/null"}
    if old_is_null and new_is_null:
        raise PatchApplyError("Unified diff has /dev/null on both sides")
    if new_is_null:
        return old_target, "delete"
    if old_is_null:
        return new_target, "create"
    return new_target, "modify"


def _strip_ab_prefix(candidate: str) -> str:
    if candidate.startswith(("a/", "b/")):
        return candidate[2:]
    return candidate


def _clear_python_bytecode(path) -> None:
    if path.suffix != ".py":
        return
    cache_dir = path.parent / "__pycache__"
    if not cache_dir.exists():
        return
    for cached in cache_dir.glob(f"{path.stem}.*.pyc"):
        cached.unlink(missing_ok=True)
