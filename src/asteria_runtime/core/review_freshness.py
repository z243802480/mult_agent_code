"""Content binding for Review consumption; never an authorization grant or coverage claim."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from asteria_runtime.core.content_preservation import PROTECTED
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator, SchemaValidationError

MAX_FILES = 10_020
MAX_BYTES = 138_412_032
RUN_INPUTS = {"goal_spec.json", "task_plan.json"}
SCOPE = "bound_goal_tasks_artifacts_guidance_and_observed_dependencies"


def _relative(value: str, root: Path) -> str:
    path = Path(value)
    return path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()


def _path(root: Path, run_dir: Path, kind: str, relative: str, protected: list[str]) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or PurePosixPath(relative).is_absolute()
        or "\\" in relative
        or ":" in relative
        or ".." in parts
    ):
        raise PermissionError("Invalid bound input path")
    if kind == "run":
        if relative not in RUN_INPUTS:
            raise PermissionError("Not a runtime review input")
        base = run_dir
        path = base / relative
    else:
        if kind != "workspace" or any(
            p in {".git", ".asteria", "secrets"}
            or p.startswith(".env")
            or p in {"id_rsa", "id_ed25519", "model.routes.local.ps1", "model.routes.local.json"}
            for p in parts
        ):
            raise PermissionError("Protected bound input")
        base = root
        path = PathGuard(root, [*PROTECTED, *protected]).resolve_for_read(relative)
    # A later link/junction replacement must not make a read cross its original boundary.
    candidate = base
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise PermissionError("Linked bound input")
    return path


def _row(
    root: Path,
    run_dir: Path,
    kind: str,
    relative: str,
    protected: list[str],
    *,
    expected_json: dict | None = None,
    expected_content: str | None = None,
    expected_text: str | None = None,
) -> dict:
    path = _path(root, run_dir, kind, relative, protected)
    if not path.exists():
        if expected_text or expected_json is not None or expected_content is not None:
            raise ValueError("Observed input disappeared before binding")
        return {"root": kind, "path": relative, "exists": False, "bytes": 0, "sha256": None}
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Bound input exceeds file limits")
    with path.open("rb") as stream:
        body = stream.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Bound input grew beyond limits")
    if expected_json is not None and json.loads(body) != expected_json:
        raise ValueError("Runtime input changed before binding")
    if (
        expected_text is not None
        and body.decode("utf8").replace("\r\n", "\n").replace("\r", "\n") != expected_text
    ):
        raise ValueError("Guidance changed before binding")
    if (
        expected_content is not None
        and hashlib.sha256("\n".join(body.decode("utf8").splitlines()).encode("utf8")).hexdigest()
        != expected_content
    ):
        raise ValueError("Artifact changed before binding")
    return {
        "root": kind,
        "path": relative,
        "exists": True,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def capture_review_binding(
    root: Path, run_dir: Path, artifacts: dict, protected: list[str], *, goal: dict, board: dict
) -> dict:
    binding: dict = {
        "schema_version": "0.1.0",
        "run_id": run_dir.name,
        "artifact_evidence_id": artifacts["evidence_id"],
        "scope": SCOPE,
        "complete": True,
        "files": [],
        "problems": [],
    }
    targets = [("run", p) for p in sorted(RUN_INPUTS)] + [("workspace", "AGENTS.md")]
    contents = {}
    for item in artifacts["files"]:
        try:
            relative = _relative(item["path"], root)
            targets.append(("workspace", relative))
            if item["status"] == "complete":
                contents[relative] = item["content_sha256"]
        except (ValueError, TypeError):
            binding["problems"].append("artifact_path_unavailable")
    guidance = artifacts.get("review_basis", {}).get("project_guidance", {})
    for kind, relative in dict.fromkeys(targets):
        try:
            expected = (
                {"goal_spec.json": goal, "task_plan.json": board}.get(relative)
                if kind == "run"
                else None
            )
            text = (
                guidance.get("content")
                if guidance.get("status") in {"complete", "absent"}
                and kind == "workspace"
                and relative == "AGENTS.md"
                else None
            )
            binding["files"].append(
                _row(
                    root,
                    run_dir,
                    kind,
                    relative,
                    protected,
                    expected_json=expected,
                    expected_content=contents.get(relative) if kind == "workspace" else None,
                    expected_text=text,
                )
            )
        except (OSError, ValueError, PermissionError, UnicodeError):
            binding["problems"].append(f"input_unavailable:{kind}/{relative}")
    binding["complete"] = not binding["problems"] and artifacts["complete"]
    return binding


def add_review_dependencies(binding: dict, manifest: list[dict]) -> None:
    existing = {(r["root"], r["path"]): r for r in binding["files"]}
    for entry in manifest:
        row = {
            "root": "workspace",
            "path": entry["path"],
            "exists": True,
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
        key = ("workspace", entry["path"])
        if key in existing and existing[key] != row:
            binding["problems"].append(f"input_changed_before_check:{entry['path']}")
        elif key not in existing:
            binding["files"].append(row)
            existing[key] = row
    if len(binding["files"]) > MAX_FILES or sum(r["bytes"] for r in binding["files"]) > MAX_BYTES:
        binding["problems"].append("binding_limit_exceeded")
    binding["complete"] = binding["complete"] and not binding["problems"]


def review_freshness(root: Path, run_dir: Path, report: dict, validator: SchemaValidator) -> dict:
    result = {
        "status": "unbound",
        "reason": "Review has no verifiable input binding; review current inputs before accepting.",
        "changed_inputs": [],
        "scope": "bound_inputs_only_not_full_workspace_or_semantic_coverage",
    }
    binding = (report.get("artifact_eval") or {}).get("review_binding")
    if not isinstance(binding, dict):
        return result
    try:
        validator.validate("review_binding", binding)
        if binding["schema_version"] != "0.1.0" or binding["scope"] != SCOPE:
            raise ValueError("Unsupported binding contract")
        evidence = (report.get("artifact_eval") or {}).get("current_artifacts_evidence") or {}
        if not isinstance(evidence, dict):
            raise ValueError("Invalid artifact evidence metadata")
        if (
            report.get("run_id") != run_dir.name
            or binding["run_id"] != run_dir.name
            or binding["artifact_evidence_id"] != evidence.get("evidence_id")
            or evidence.get("complete") is not True
        ):
            raise ValueError("Review binding identity mismatch")
        evidence_id = binding["artifact_evidence_id"]
        if (
            not evidence_id.startswith("review-artifacts-")
            or Path(evidence_id).name != evidence_id
            or "/" in evidence_id
            or "\\" in evidence_id
        ):
            raise ValueError("Invalid artifact evidence identity")
        snapshot_path = run_dir / (evidence_id + ".json")
        if snapshot_path.is_symlink() or getattr(snapshot_path, "is_junction", lambda: False)():
            raise PermissionError("Linked artifact snapshot")
        snapshot = JsonStore(validator).read(snapshot_path, "review_artifacts")
        if (
            snapshot["run_id"] != run_dir.name
            or snapshot["evidence_id"] != evidence_id
            or not snapshot["complete"]
        ):
            raise ValueError("Artifact snapshot is not complete and bound")
        required = {("run", p) for p in RUN_INPUTS} | {("workspace", "AGENTS.md")}
        required |= {("workspace", _relative(row["path"], root)) for row in snapshot["files"]}
        must_exist = {("run", p) for p in RUN_INPUTS} | {
            ("workspace", _relative(row["path"], root)) for row in snapshot["files"]
        }
        keys = [(r["root"], r["path"]) for r in binding["files"]]
        if (
            not required.issubset(keys)
            or len(set(keys)) != len(keys)
            or len(keys) > MAX_FILES
            or sum(r["bytes"] for r in binding["files"]) > MAX_BYTES
        ):
            raise ValueError("Review binding input set is invalid")
        if not binding["complete"] or binding["problems"]:
            raise ValueError("Review binding is incomplete")
        policies = root / ".asteria/policies.json"
        policy = JsonStore(validator).read(policies, "policy_config") if policies.exists() else {}
        protected = policy.get("protected_paths", [])
        changed = []
        for row in binding["files"]:
            if (row["root"], row["path"]) in must_exist and row["exists"] is not True:
                raise ValueError("Required reviewed input is absent")
            # Size mismatch is enough: never read an unexpectedly huge replacement.
            path = _path(root, run_dir, row["root"], row["path"], protected)
            if path.exists() and (not path.is_file() or path.stat().st_size != row["bytes"]):
                changed.append(row["root"] + "/" + row["path"])
            elif _row(root, run_dir, row["root"], row["path"], protected) != row:
                changed.append(row["root"] + "/" + row["path"])
        return {
            **result,
            "status": "changed" if changed else "current",
            "changed_inputs": changed,
            "reason": "Bound Review inputs changed; review the current inputs again."
            if changed
            else "Bound Review input contents match; this is not a semantic coverage certification.",
        }
    except (OSError, ValueError, TypeError, KeyError, PermissionError, SchemaValidationError):
        return {
            **result,
            "status": "unavailable",
            "reason": "Review input binding cannot be verified safely; review current inputs before accepting.",
        }
