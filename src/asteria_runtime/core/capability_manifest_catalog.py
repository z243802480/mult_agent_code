from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def manifest_internal_tools(manifest: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for tool in manifest.get("direct_tools") or []:
        if isinstance(tool, dict) and tool.get("name"):
            names.add(str(tool["name"]))
    model_surface = ((manifest.get("boundaries") or {}).get("model_tool_surface") or {}).get("tools")
    if isinstance(model_surface, list):
        for tool in model_surface:
            if not isinstance(tool, dict):
                continue
            internal = tool.get("internal_tool") or tool.get("name")
            if internal:
                names.add(str(internal))
    return names


def manifest_named_capabilities(manifest: dict[str, Any], capability_type: str) -> set[str]:
    key_by_type = {
        "skill": "skills",
        "mcp": "mcp_tools",
        "deferred": "deferred_tools",
        "verification": "verification",
    }
    key = key_by_type.get(capability_type)
    if not key:
        return set()
    names: set[str] = set()
    for item in manifest.get(key) or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    if capability_type == "mcp":
        for item in manifest.get("deferred_tools") or []:
            if isinstance(item, dict) and item.get("name") == "tool_search":
                names.add("tool_search")
    return names


def capability_manifest_catalog_audit(run_dir: Path) -> dict[str, Any]:
    """Compare task capability catalogs with persisted CapabilityManifest evidence."""

    dispatch_path = run_dir / "agent_loop_dispatch.json"
    if not dispatch_path.exists():
        return {
            "status": "skipped",
            "aligned": True,
            "reason": "no agent_loop_dispatch evidence",
            "mismatches": [],
        }

    manifest = _latest_manifest(run_dir)
    if not manifest:
        return {
            "status": "skipped",
            "aligned": True,
            "reason": "no capability manifest evidence",
            "mismatches": [],
        }

    try:
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "status": "skipped",
            "aligned": True,
            "reason": "agent_loop_dispatch unreadable",
            "mismatches": [],
        }

    internal_tools = manifest_internal_tools(manifest)
    mismatches: list[dict[str, Any]] = []
    for task in dispatch.get("task_dispatch") or []:
        if not isinstance(task, dict):
            continue
        catalog = task.get("capability_catalog") or {}
        task_id = task.get("task_id")
        for entry in catalog.get("entries") or []:
            if not isinstance(entry, dict) or entry.get("selection_state") != "selected":
                continue
            capability_type = str(entry.get("capability_type") or "")
            name = str(entry.get("name") or "")
            if capability_type == "tool":
                internal = str((entry.get("metadata") or {}).get("internal_tool") or name)
                if internal and internal not in internal_tools:
                    mismatches.append(
                        {
                            "task_id": task_id,
                            "capability_type": capability_type,
                            "name": name,
                            "internal_tool": internal,
                            "reason": "selected catalog tool missing from manifest surface",
                        }
                    )
                continue
            manifest_names = manifest_named_capabilities(manifest, capability_type)
            if name and manifest_names and name not in manifest_names:
                if capability_type == "mcp" and "/" in name:
                    server = name.split("/", 1)[0]
                    if server in manifest_names:
                        continue
                mismatches.append(
                    {
                        "task_id": task_id,
                        "capability_type": capability_type,
                        "name": name,
                        "reason": "selected catalog capability missing from manifest layer",
                    }
                )

    return {
        "status": "checked",
        "aligned": not mismatches,
        "manifest_tool_count": len(internal_tools),
        "task_dispatch_count": len(
            [item for item in (dispatch.get("task_dispatch") or []) if isinstance(item, dict)]
        ),
        "mismatches": mismatches,
    }


def _latest_manifest(run_dir: Path) -> dict[str, Any] | None:
    candidates = sorted(run_dir.glob("prompt_envelope*.json"))
    for path in reversed(candidates):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        manifest = data.get("capability_manifest")
        if isinstance(manifest, dict):
            return manifest
    return None
