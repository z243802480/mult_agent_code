from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.capability_manifest_catalog import (
    capability_manifest_catalog_audit,
    manifest_internal_tools,
)


def test_manifest_internal_tools_collects_direct_and_model_surface_tools() -> None:
    manifest = {
        "direct_tools": [{"name": "read_file"}],
        "boundaries": {
            "model_tool_surface": {
                "tools": [{"name": "grep", "internal_tool": "search_text"}],
            }
        },
    }

    assert manifest_internal_tools(manifest) == {"read_file", "search_text"}


def test_capability_manifest_catalog_audit_flags_missing_selected_tools(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir()
    (run_dir / "prompt_envelope_execute.json").write_text(
        json.dumps(
            {
                "capability_manifest": {
                    "direct_tools": [{"name": "read_file"}],
                    "boundaries": {"model_tool_surface": {"tools": []}},
                    "skills": [],
                    "mcp_tools": [],
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "task_id": "task-0001",
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "tool",
                                    "name": "write_file",
                                    "selection_state": "selected",
                                    "metadata": {"internal_tool": "write_file"},
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    audit = capability_manifest_catalog_audit(run_dir)

    assert audit["status"] == "checked"
    assert audit["aligned"] is False
    assert audit["mismatches"][0]["internal_tool"] == "write_file"


def test_capability_manifest_catalog_audit_passes_when_selected_tools_match(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir()
    (run_dir / "prompt_envelope_execute.json").write_text(
        json.dumps(
            {
                "capability_manifest": {
                    "direct_tools": [{"name": "read_file"}, {"name": "write_file"}],
                    "boundaries": {
                        "model_tool_surface": {
                            "tools": [{"name": "grep", "internal_tool": "search_text"}],
                        }
                    },
                    "skills": [],
                    "mcp_tools": [],
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "task_dispatch": [
                    {
                        "task_id": "task-0001",
                        "capability_catalog": {
                            "entries": [
                                {
                                    "capability_type": "tool",
                                    "name": "write_file",
                                    "selection_state": "selected",
                                    "metadata": {"internal_tool": "write_file"},
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    audit = capability_manifest_catalog_audit(run_dir)

    assert audit["aligned"] is True
    assert audit["mismatches"] == []
