from __future__ import annotations

from asteria_runtime.core.capability_catalog import task_capability_catalog


def test_task_capability_catalog_records_selected_skipped_and_blocked_reasons() -> None:
    catalog = task_capability_catalog(
        task={
            "task_id": "task-1",
            "task_kind": "research",
            "allowed_tools": ["read_file", "search_text", "run_command"],
            "allowed_mcp": ["docs"],
            "risk": "medium",
        },
        runtime_tool_names=["read_file", "search_text", "run_command"],
        permission_mode="reviewed_auto",
        skill_catalog=[{"name": "documents", "scope": "workspace"}],
        mcp_servers=[{"name": "docs", "tools": ["search"]}],
        allow_shell=True,
    )

    entries = {(item["capability_type"], item["name"]): item for item in catalog["entries"]}

    assert catalog["summary"]["visible"] > 0
    assert entries[("tool", "read_file")]["selection_state"] == "selected"
    assert entries[("mcp", "docs")]["selection_state"] == "selected"
    assert entries[("mcp", "docs/search")]["selection_state"] == "selected"
    assert entries[("mcp", "docs/search")]["metadata"]["server"] == "docs"
    assert entries[("skill", "documents")]["selection_state"] == "blocked"
    assert entries[("skill", "documents")]["blocked_reason"]
    assert entries[("tool", "write_file")]["selection_state"] == "blocked"
    assert entries[("tool", "write_file")]["selection_reason"]
