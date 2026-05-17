from __future__ import annotations

import fnmatch
from pathlib import Path


class PathPolicyError(PermissionError):
    pass


class PathGuard:
    def __init__(self, root: Path, protected_paths: list[str]) -> None:
        self.root = root.resolve()
        self.protected_paths = protected_paths

    def resolve_for_read(self, path: str | Path) -> Path:
        resolved = self._resolve_inside_root(path)
        self._ensure_not_protected(resolved)
        return resolved

    def resolve_for_write(self, path: str | Path) -> Path:
        resolved = self._resolve_inside_root(path)
        self._ensure_not_protected(resolved)
        return resolved

    def _resolve_inside_root(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathPolicyError(f"Path escapes workspace root: {path}") from exc
        return resolved

    def _ensure_not_protected(self, path: Path) -> None:
        rel = path.relative_to(self.root).as_posix()
        for pattern in self.protected_paths:
            normalized = pattern.replace("\\", "/")
            if normalized.endswith("/"):
                if rel == normalized.rstrip("/") or rel.startswith(normalized):
                    raise PathPolicyError(f"Path is protected by policy: {rel}")
            elif fnmatch.fnmatch(rel, normalized):
                raise PathPolicyError(f"Path is protected by policy: {rel}")
