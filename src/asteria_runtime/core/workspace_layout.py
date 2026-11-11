"""Shared session write surfaces for observed workspace directory names."""

from collections.abc import Iterable


def observed_directory_write_scopes(names: Iterable[str]) -> list[str]:
    excluded = {"secrets", "node_modules", "__pycache__", "venv", "dist", "build"}
    return list(dict.fromkeys(
        f"{name}/" for name in names
        if name and not name.startswith(".") and name not in excluded
        and not any(separator in name for separator in ("/", "\\", ":"))
    ))
