"""Denied attempts share the real call ledger/IDs without executing or charging tools."""

from pathlib import Path

import pytest

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionDenied, ToolPermissionPolicy
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.tools.registry import ToolRegistry


def test_denied_then_real_read_and_tool_failure_have_distinct_matching_ids(tmp_path: Path):
    validator = SchemaValidator(Path("schemas"))
    ctx = RuntimeContext(root=tmp_path, run_id="run-ledger", policy={"protected_paths": []},
                         validator=validator,
                         budget=BudgetController({"budgets": {"max_tool_calls_per_goal": 1000}}))
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    gateway = ToolExecutionGateway(registry, ToolPermissionPolicy(tmp_path, validator))
    task = {"task_id": "task-0001", "allowed_tools": ["read_file"],
            "task_kind": "implementation", "read_scope": ["allowed/"]}
    (tmp_path / "allowed").mkdir()
    (tmp_path / "allowed/ok.txt").write_text("visible", encoding="utf-8")

    with pytest.raises(ToolPermissionDenied):
        gateway.run_tool_calls([{"tool_name": "read_file", "args": {"path": "denied.txt"}}], task, ctx)
    result = gateway.run_tool_calls(
        [{"tool_name": "read_file", "args": {"path": "allowed/ok.txt"}}], task, ctx)
    assert result[0].ok
    failed = gateway.run_tool_calls(
        [{"tool_name": "read_file", "args": {"path": "allowed/missing.txt"}}], task, ctx,
        stop_on_failure=False)
    assert not failed[0].ok

    store = JsonlStore(validator)
    calls = store.read_all(ctx.run_dir / "tool_calls.jsonl", "tool_call")
    observations = store.read_all(ctx.run_dir / "tool_observations.jsonl", "tool_observation")
    assert [row["status"] for row in calls] == ["denied", "success", "failure"]
    expected = ["toolcall-0001", "toolcall-0002", "toolcall-0003"]
    assert [row["tool_call_id"] for row in calls] == expected
    assert [row["tool_call_id"] for row in observations] == expected
    assert ctx.budget.usage.tool_calls == 2  # Pre-registry refusal did not execute a tool.
