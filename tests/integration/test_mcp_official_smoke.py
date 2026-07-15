import os
import shutil
import time
from pathlib import Path

import pytest

from asteria_runtime.core.mcp_adapter import McpAdapter, McpServerConfig
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


pytestmark = pytest.mark.mcp_official_smoke


@pytest.mark.real_provider_smoke
def test_official_everything_mcp_server_stdio_smoke() -> None:
    # Runs for real in the scheduled `.github/workflows/nightly.yml` job (which sets the env var and
    # provides npx). It skips in the per-push suite by design — it needs npx + network, not a model
    # key — so the skip here is covered, not a coverage gap.
    if os.environ.get("ASTERIA_MCP_OFFICIAL_SMOKE") != "1":
        pytest.skip("Set ASTERIA_MCP_OFFICIAL_SMOKE=1 to run the official MCP server smoke.")
    if not os.environ.get("ASTERIA_MCP_EVERYTHING_INDEX") and shutil.which("npx") is None:
        pytest.skip("npx is required for @modelcontextprotocol/server-everything smoke.")

    validator = SchemaValidator(Path.cwd() / "schemas")
    root = Path.cwd()
    run_dir = root / ".asteria" / "verification" / f"mcp_official_smoke_pytest_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    context = RuntimeContext(
        root=root,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=validator,
        run_dir_override=run_dir,
    )
    command = _server_command()
    adapter = McpAdapter.from_configs([McpServerConfig(name="everything", command=command)])

    try:
        result = adapter.invoke_tool(
            context=context,
            task={
                "task_id": "task-1",
                "task_kind": "research",
                "allowed_mcp": ["everything"],
            },
            server_name="everything",
            tool_name="echo",
            arguments={"message": "asteria mcp smoke ok"},
        )
    finally:
        adapter.close()

    invocations = JsonlStore(validator).read_all(
        run_dir / "mcp_invocations.jsonl",
        schema_name=None,
    )
    progress = JsonlStore(validator).read_all(
        run_dir / "user_progress.jsonl",
        "user_progress_event",
    )

    assert result.ok is True
    assert "asteria mcp smoke ok" in str(result.data)
    assert invocations[0]["server_name"] == "everything"
    assert invocations[0]["tool_name"] == "echo"
    assert invocations[0]["status"] == "success"
    assert progress[0]["event_type"] == "permission_decision"
    assert progress[1]["data"]["capability_type"] == "mcp"


def _server_command() -> list[str]:
    installed = os.environ.get("ASTERIA_MCP_EVERYTHING_INDEX")
    if installed:
        return ["node", installed, "stdio"]
    return ["npx", "-y", "@modelcontextprotocol/server-everything", "stdio"]
