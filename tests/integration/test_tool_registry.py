import json
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.tools.command_tools import RunCommandTool
from agent_runtime.tools.file_tools import ReadFileTool, WriteFileTool
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.search_tools import SearchTextTool


def policy(max_tool_calls: int = 20) -> dict:
    return {
        "budgets": {
            "max_model_calls_per_goal": 60,
            "max_tool_calls_per_goal": max_tool_calls,
            "max_total_minutes_per_goal": 30,
            "max_iterations_per_goal": 8,
            "max_repair_attempts_total": 5,
            "max_repair_attempts_per_task": 2,
            "max_research_calls": 5,
            "max_user_decisions": 5,
        },
        "permissions": {
            "allow_network": False,
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_secret_file_read": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        },
        "protected_paths": [".env", "secrets/", ".git/"],
    }


def context(tmp_path: Path, max_tool_calls: int = 20) -> RuntimeContext:
    run_id = "run-20260427-0001"
    run_dir = tmp_path / ".agent" / "runs" / run_id
    run_dir.mkdir(parents=True)
    validator = SchemaValidator(Path("schemas"))
    return RuntimeContext(
        root=tmp_path,
        run_id=run_id,
        policy=policy(max_tool_calls=max_tool_calls),
        validator=validator,
        event_logger=EventLogger(run_dir / "events.jsonl", validator),
        budget=BudgetController(policy(max_tool_calls=max_tool_calls), run_id=run_id),
    )


def registry() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(SearchTextTool())
    tools.register(RunCommandTool(default_timeout_seconds=10))
    return tools


def test_file_tools_write_read_and_log(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    tools = registry()

    write = tools.call("write_file", ctx, path="notes/example.txt", content="hello world")
    read = tools.call("read_file", ctx, path="notes/example.txt")

    assert write.ok
    assert read.ok
    assert read.data["content"] == "hello world"

    tool_calls = (ctx.run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    events = [
        json.loads(line)
        for line in (ctx.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(tool_calls) == 2
    assert "file_backup_created" in {event["type"] for event in events}
    assert len([event for event in events if event["type"] == "tool_called"]) == 2


def test_search_tool_finds_text(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    tools = registry()
    tools.call("write_file", ctx, path="src/a.txt", content="alpha\nneedle\n")

    result = tools.call("search_text", ctx, pattern="needle", path="src")

    assert result.ok
    assert result.data["matches"][0]["line"] == 2


def test_protected_read_is_denied_and_logged(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    tools = registry()
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    result = tools.call("read_file", ctx, path=".env")

    assert not result.ok
    assert result.status == "denied"
    row = json.loads((ctx.run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "denied"


def test_command_tool_runs_safe_command_and_blocks_dangerous(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    tools = registry()

    safe = tools.call("run_command", ctx, command="python --version")
    denied = tools.call("run_command", ctx, command="Remove-Item important.txt")

    assert safe.ok
    assert not denied.ok
    assert denied.status == "denied"


def test_tool_registry_budget_denies_before_execution(tmp_path: Path) -> None:
    ctx = context(tmp_path, max_tool_calls=1)
    tools = registry()

    first = tools.call("write_file", ctx, path="a.txt", content="ok")
    second = tools.call("write_file", ctx, path="b.txt", content="blocked")

    assert first.ok
    assert not second.ok
    assert second.status == "denied"
    assert not (tmp_path / "b.txt").exists()
