"""Source-bound whole-line preservation, independent of language and verifier choice."""

from __future__ import annotations

import hashlib
import json

from asteria_runtime.core.edit_boundary import validate_edit_boundary
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError

MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 4_194_304
MAX_LINES = 65_536
PROTECTED = [
    ".asteria/",
    ".git/",
    ".env",
    ".env.*",
    "secrets/",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "*/.env*",
    "*/id_rsa",
    "*/id_ed25519",
    "*/secrets/*",
    "*/.git/*",
    "*/.asteria/*",
]


def normalize_content_preservation(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > 32:
        raise SchemaValidationError("content_preservation must be a list of at most 32 files")
    result: list[dict] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "mode"}
            or item["mode"] != "existing_lines"
            or not isinstance(item["path"], str)
        ):
            raise SchemaValidationError(
                "content_preservation requires path and mode=existing_lines"
            )
        path = validate_edit_boundary({"mode": "restricted", "paths": [item["path"]]})["paths"][0]
        if path.endswith("/") or any(c in path for c in "*?["):
            raise SchemaValidationError("content_preservation requires a literal file path")
        if any(row["path"] == path for row in result):
            raise SchemaValidationError("Duplicate content preservation path")
        result.append({"path": path, "mode": "existing_lines"})
    return result


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(constraints: list[dict]) -> str:
    return _sha(json.dumps(constraints, sort_keys=True, separators=(",", ":")).encode())


def _read(context: RuntimeContext, path: str) -> bytes:
    guard = PathGuard(context.root, [*PROTECTED, *context.policy.get("protected_paths", [])])
    target = guard.resolve_for_read(path)
    with target.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Content preservation file exceeds bounded read limit")
    return data


def capture_content_preservation(context: RuntimeContext, goal: dict) -> None:
    constraints = normalize_content_preservation(goal.get("content_preservation", []))
    if not constraints:
        return
    if context.run_dir is None:
        raise ValueError("Content preservation requires a durable run")
    path = context.run_dir / "content_preservation.json"
    store = JsonStore(context.validator)
    if path.exists():
        _load(context, goal, constraints)  # Never rebase onto already edited content.
        return
    files = []
    total_bytes = total_lines = 0
    for item in constraints:
        data = _read(context, item["path"])
        hashes = [_sha(line) for line in data.splitlines(keepends=True)]
        total_bytes += len(data)
        total_lines += len(hashes)
        if total_bytes > MAX_TOTAL_BYTES or total_lines > MAX_LINES:
            raise ValueError("Content preservation snapshot exceeds bounded capacity")
        files.append(
            {
                "path": item["path"],
                "content_sha256": _sha(data),
                "line_sha256": hashes,
                "lines_sha256": _sha(json.dumps(hashes).encode()),
            }
        )
    store.write(
        path,
        {
            "schema_version": "0.1.0",
            "goal_id": goal["goal_id"],
            "constraints_sha256": _fingerprint(constraints),
            "files": files,
        },
        "content_preservation",
    )


def _load(context: RuntimeContext, goal: dict, constraints: list[dict]) -> dict:
    if context.run_dir is None:
        raise ValueError("Missing content preservation run")
    saved = JsonStore(context.validator).read(
        context.run_dir / "content_preservation.json", "content_preservation"
    )
    if (
        saved["goal_id"] != goal["goal_id"]
        or saved["constraints_sha256"] != _fingerprint(constraints)
        or [f["path"] for f in saved["files"]] != [c["path"] for c in constraints]
    ):
        raise ValueError("Content preservation source binding changed")
    if any(
        item["lines_sha256"] != _sha(json.dumps(item["line_sha256"]).encode())
        for item in saved["files"]
    ):
        raise ValueError("Content preservation line evidence is damaged")
    return saved


def content_preservation_violations(context: RuntimeContext, goal: dict) -> list[str]:
    try:
        constraints = normalize_content_preservation(goal.get("content_preservation", []))
        if not constraints:
            return []
        saved = _load(context, goal, constraints)
        violations = []
        for item in saved["files"]:
            # Ordered subsequence of COMPLETE byte lines, including endings and duplicates.
            # Greedy matching is linear and cannot accept a comment appended to an old line.
            current = iter(
                _sha(line) for line in _read(context, item["path"]).splitlines(keepends=True)
            )
            if not all(
                any(actual == expected for actual in current) for expected in item["line_sha256"]
            ):
                violations.append(f"existing lines were not preserved: {item['path']}")
        return violations
    except (OSError, ValueError, PermissionError, KeyError, TypeError) as exc:
        return [f"content preservation evidence unavailable: {type(exc).__name__}"]
