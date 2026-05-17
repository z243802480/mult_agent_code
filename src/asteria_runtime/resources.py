from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def schema_dir() -> Path:
    repo_path = Path(__file__).resolve().parents[2] / "schemas"
    if repo_path.exists():
        return repo_path
    return Path(str(files("asteria_runtime") / "schemas"))


def template_path(name: str) -> Path:
    repo_path = Path(__file__).resolve().parents[2] / "templates" / name
    if repo_path.exists():
        return repo_path
    return Path(str(files("asteria_runtime") / "templates" / name))
