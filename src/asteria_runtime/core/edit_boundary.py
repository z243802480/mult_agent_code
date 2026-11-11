"""A goal's explicit edit ceiling, separate from deliverables and read access."""

from __future__ import annotations

import ntpath
import os
import posixpath
from pathlib import Path

from asteria_runtime.storage.schema_validator import SchemaValidationError


def _relative_path(path: str) -> str:
    value = path.replace("\\", "/")
    if (
        not value.strip()
        or "\0" in value
        or value.startswith("/")
        or ntpath.splitdrive(value)[0]
        or ".." in value.split("/")
    ):
        raise SchemaValidationError("edit_boundary paths must stay relative to the workspace")
    normalized = posixpath.normpath(value)
    if normalized == ".":
        raise SchemaValidationError("use open mode instead of a workspace-root path")
    return normalized + ("/" if value.endswith("/") else "")


def validate_edit_boundary(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"mode", "paths"}:
        raise SchemaValidationError("edit_boundary requires only mode and paths")
    mode, paths = value["mode"], value["paths"]
    if (
        not isinstance(mode, str)
        or mode not in {"open", "restricted"}
        or not isinstance(paths, list)
    ):
        raise SchemaValidationError("edit_boundary mode/paths are invalid")
    if any(not isinstance(path, str) for path in paths):
        raise SchemaValidationError("edit_boundary paths must be strings")
    normalized = list(dict.fromkeys(_relative_path(path) for path in paths))
    if mode == "open" and normalized:
        raise SchemaValidationError("open edit_boundary must have empty paths")
    return {"mode": mode, "paths": normalized}


def edit_boundary_allows(boundary: object, path: str, *, root: Path | None = None) -> bool:
    if boundary is None:
        return True
    try:
        ceiling = validate_edit_boundary(boundary)
        if ceiling["mode"] == "open":
            return True
        candidate = os.path.normcase(_relative_path(path).rstrip("/")).replace("\\", "/")
    except (SchemaValidationError, TypeError, AttributeError):
        return False
    for entry in ceiling["paths"]:
        grant = os.path.normcase(entry).replace("\\", "/")
        if candidate != grant.rstrip("/") and not (
            grant.endswith("/") and candidate.startswith(grant)
        ):
            continue
        if root is None:
            return True
        try:
            actual = (root / path).resolve()
            allowed = (root / entry).resolve()
            if not actual.is_relative_to(root.resolve()) or not allowed.is_relative_to(
                root.resolve()
            ):
                continue
            if actual == allowed or (entry.endswith("/") and actual.is_relative_to(allowed)):
                return True
        except (OSError, RuntimeError):
            continue
    return False
