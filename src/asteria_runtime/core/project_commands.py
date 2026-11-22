"""Discover command entry points from declarations, without executing or certifying them."""
from __future__ import annotations

import configparser
import hashlib
import json
from pathlib import Path
import tomllib


def discover_project_commands(root: Path) -> tuple[dict, dict]:
    commands: dict[str, str | None] = dict.fromkeys(
        ("install", "run", "test", "lint", "typecheck", "build", "format"), None,
    )
    sources: dict[str, dict] = {}

    def read(name: str) -> bytes | None:
        path = root / name
        try:
            if path.is_symlink() or not path.is_file():
                return None
            with path.open("rb") as handle:
                raw = handle.read(262_145)
            return raw if len(raw) <= 262_144 else None
        except OSError:
            return None

    def load(name: str, parser) -> tuple[dict, bytes]:
        raw = read(name)
        if raw is None:
            return {}, b""
        try:
            data = parser(raw.decode("utf8"))
        except (ValueError, UnicodeError):
            return {}, b""
        return (data, raw) if isinstance(data, dict) else ({}, b"")

    def add(kind: str, command: str, name: str, selector: str, raw: bytes, basis="tool_configuration") -> None:
        if commands[kind] is None:
            commands[kind] = command
            sources[kind] = {"path": name, "selector": selector, "content_sha256": hashlib.sha256(raw).hexdigest(),
                             "basis": basis}

    pyproject, raw = load("pyproject.toml", tomllib.loads)
    tool = pyproject.get("tool", {})
    if isinstance(tool, dict):
        pytest = tool.get("pytest", {})
        if isinstance(pytest, dict) and isinstance(pytest.get("ini_options"), dict):
            add("test", "pytest", "pyproject.toml", "tool.pytest.ini_options", raw)
        elif "pytest" in tool and isinstance(pytest, dict):  # Native TOML configuration (pytest 9+).
            add("test", "pytest", "pyproject.toml", "tool.pytest", raw)
        if isinstance(tool.get("ruff"), dict):
            add("lint", "ruff check .", "pyproject.toml", "tool.ruff", raw)
            add("format", "ruff format .", "pyproject.toml", "tool.ruff", raw)
        mypy = tool.get("mypy")
        targets = mypy.get("files") if isinstance(mypy, dict) else None
        if ((isinstance(targets, str) and targets.strip()) or
                (isinstance(targets, list) and targets and all(isinstance(t, str) and t.strip() for t in targets))):
            add("typecheck", "mypy", "pyproject.toml", "tool.mypy.files", raw)

    for name, section in (("pytest.ini", "pytest"), (".pytest.ini", "pytest"),
                          ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        content = read(name)
        if content is None:
            continue
        try:
            ini = configparser.ConfigParser(interpolation=None)
            ini.read_string(content.decode("utf8"))
        except (configparser.Error, UnicodeError):
            continue
        if ini.has_section(section):
            add("test", "pytest", name, section, content)

    for name in ("ruff.toml", ".ruff.toml"):
        config, raw = load(name, tomllib.loads)
        if config or raw:
            add("lint", "ruff check .", name, "", raw)
            add("format", "ruff format .", name, "", raw)

    package, raw = load("package.json", json.loads)
    if package or raw:
        add("install", "npm install", "package.json", "", raw, "package_manifest")
        scripts = package.get("scripts", {})
        if isinstance(scripts, dict):
            for kind, script in (("run", "dev"), ("test", "test"), ("lint", "lint"),
                                 ("typecheck", "typecheck"), ("build", "build"), ("format", "format")):
                value = scripts.get(script)
                if isinstance(value, str) and value.strip():
                    add(kind, "npm test" if kind == "test" else "npm run " + script,
                        "package.json", "scripts." + script, raw, "package_script")
    return commands, sources
