from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from asteria_runtime.core.permission_policy import normalize_permission_mode
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SCHEMA_VERSION = "0.1.0"


def build_workspace_envelope(
    *,
    workspace_root: Path,
    permission_level: str,
    input_roots: list[Path] | None = None,
    output_root: Path | None = None,
    candidate_workspace_policy: str = "controlled_patch",
    worktree_policy: str | None = None,
    read_scope: list[str] | None = None,
    write_scope: list[str] | None = None,
    artifact_policy: str = "workspace_artifacts",
    artifact_root: Path | None = None,
    git_policy: str = "detect",
) -> dict[str, Any]:
    root = workspace_root.resolve()
    output = (output_root or root).resolve()
    artifacts = (artifact_root or root / ".asteria" / "artifacts").resolve()
    inputs = [item.resolve() for item in (input_roots or [root])]
    read = read_scope or [str(item) for item in inputs]
    write = write_scope or [str(output)]
    worktree = worktree_policy or candidate_workspace_policy
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": workspace_id(root),
        "workspace_root": str(root),
        "input_roots": [str(item) for item in inputs],
        "output_root": str(output),
        "artifact_root": str(artifacts),
        "candidate_workspace_policy": candidate_workspace_policy,
        "worktree_policy": worktree,
        "read_scope": read,
        "write_scope": write,
        "scope_summary": {
            "input_root_count": len(inputs),
            "read_scope_count": len(read),
            "write_scope_count": len(write),
            "output_inside_workspace": _is_relative_to(output, root),
            "artifact_root_inside_workspace": _is_relative_to(artifacts, root),
        },
        "artifact_policy": artifact_policy,
        "git_policy": git_policy,
        "permission_mode": normalize_permission_mode(permission_level),
        "created_at": now_iso(),
    }


def write_workspace_envelope(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    JsonStore(validator).write(run_dir / "workspace_envelope.json", envelope, "workspace_envelope")
    return envelope


def workspace_summary(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": envelope.get("workspace_id"),
        "workspace_root": envelope.get("workspace_root"),
        "output_root": envelope.get("output_root"),
        "artifact_root": envelope.get("artifact_root"),
        "permission_mode": envelope.get("permission_mode"),
        "candidate_workspace_policy": envelope.get("candidate_workspace_policy"),
        "worktree_policy": envelope.get("worktree_policy")
        or envelope.get("candidate_workspace_policy"),
        "git_policy": envelope.get("git_policy"),
    }


def workspace_id(root: Path) -> str:
    digest = hashlib.sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest()[:12]
    return f"workspace-{digest}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
