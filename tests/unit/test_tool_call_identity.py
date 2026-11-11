from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.skill_adapter import SkillAdapter
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.base import ToolResult
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.tools.registry import ToolRegistry


class Skill:
    def __init__(self, ok=True):
        self.ok = ok

    def invoke(self, request):
        return {"ok": self.ok, "summary": "Loaded procedure"}


class Session:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def call(self, method, params):
        self.calls += 1
        return {"content": [{"type": "text", "text": "Result"}], "isError": not self.ok}


def context(root, limit=100):
    policy = {
        "permission_mode": "reviewed_auto",
        "protected_paths": [],
        "permissions": {"allow_shell": True, "allow_network": True},
        "budgets": {"max_tool_calls_per_goal": limit},
    }
    return RuntimeContext(
        root,
        "run-identity",
        policy,
        SchemaValidator(Path("schemas")),
        budget=BudgetController(policy),
    )


def registry():
    result = ToolRegistry()
    result.register(ReadFileTool())
    return result


def rows(ctx, filename):
    return JsonlStore(ctx.validator).read_all(ctx.run_dir / filename)


@pytest.mark.parametrize("channel", ["skill", "mcp"])
@pytest.mark.parametrize("outcome", ["success", "failure", "denied"])
def test_cross_channel_success_and_failure_preserve_identity_and_single_charge(
    tmp_path, channel, outcome
):
    ctx = context(tmp_path)
    (tmp_path / "input.txt").write_text("visible")
    gateway = ToolExecutionGateway(
        registry(),
        ToolPermissionPolicy(tmp_path, ctx.validator),
        skill_adapter=SkillAdapter({"helper": Skill(outcome != "failure")}),
        mcp_adapter=McpAdapter({"server": Session(outcome != "failure")}),
    )
    task = {
        "task_id": "task-1",
        "task_kind": "implementation",
        "risk": "medium",
        "allowed_tools": ["read_file"],
        "allowed_skills": ["helper"] if outcome != "denied" else ["other"],
        "allowed_mcp": ["server"] if outcome != "denied" else ["other"],
    }
    name = "skill__helper" if channel == "skill" else "mcp__server__echo"
    result = gateway.run_tool_calls(
        [
            {"tool_name": name, "args": {}},
            {"tool_name": "read_file", "args": {"path": "input.txt"}},
        ],
        task,
        ctx,
        stop_on_failure=False,
    )
    assert result[0].ok is (outcome == "success")
    assert result[1].ok
    observations = rows(ctx, "tool_observations.jsonl")
    calls = rows(ctx, "tool_calls.jsonl")
    invocations = rows(ctx, f"{channel}_invocations.jsonl")
    ids = [o["tool_call_id"] for o in observations]
    assert len(ids) == len(set(ids)) == 2
    assert len({o["observation_id"] for o in observations}) == 2
    assert len(calls) == len(invocations) == 1
    assert invocations[0]["tool_call_id"] == ids[0]
    assert calls[0]["tool_call_id"] == ids[1]
    assert observations[0]["evidence_refs"] == [str(ctx.run_dir / f"{channel}_invocations.jsonl")]
    assert ctx.budget.usage.tool_calls == (1 if outcome == "denied" else 2)
    assert ctx.tool_call_id is None
    if channel == "mcp":
        assert gateway.mcp_adapter.sessions["server"].calls == (0 if outcome == "denied" else 1)
        if outcome == "failure":
            assert invocations[0]["status"] == "tool_error"
            assert invocations[0]["data"]["response"]["isError"] is True


@pytest.mark.parametrize("channel", ["skill", "mcp"])
def test_adapter_exception_and_later_local_call_do_not_reuse_identity(tmp_path, channel):
    class BrokenAdapter:
        def invoke(self, **kwargs):
            raise ValueError("adapter failed before invocation evidence")

        invoke_tool = invoke

    ctx = context(tmp_path)
    (tmp_path / "input.txt").write_text("visible")
    gateway = ToolExecutionGateway(
        registry(),
        ToolPermissionPolicy(tmp_path, ctx.validator),
        skill_adapter=BrokenAdapter(),
        mcp_adapter=BrokenAdapter(),
    )
    task = {"task_id": "task-1", "allowed_tools": ["read_file"]}
    name = "skill__helper" if channel == "skill" else "mcp__server__echo"
    with pytest.raises(ValueError):
        gateway.run_tool_calls([{"tool_name": name, "args": {}}], task, ctx)
    gateway.run_tool_calls([{"tool_name": "read_file", "args": {"path": "input.txt"}}], task, ctx)
    observations = rows(ctx, "tool_observations.jsonl")
    assert len({o["tool_call_id"] for o in observations}) == len(observations) == 2
    assert rows(ctx, "tool_calls.jsonl")[0]["tool_call_id"] == observations[1]["tool_call_id"]
    assert ctx.budget.usage.tool_calls == 1


def test_registry_recreation_and_concurrent_reads_preserve_history(tmp_path):
    ctx = context(tmp_path)
    (tmp_path / "input.txt").write_text("visible")
    registry().call("read_file", ctx, path="input.txt")
    prefix = (ctx.run_dir / "tool_calls.jsonl").read_bytes()
    reconstructed = replace(ctx)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: registry().call("read_file", reconstructed, path="input.txt"), range(8)
            )
        )
    assert all(r.ok for r in results)
    calls = rows(ctx, "tool_calls.jsonl")
    assert len({r["tool_call_id"] for r in calls}) == len(calls) == 9
    assert (ctx.run_dir / "tool_calls.jsonl").read_bytes().startswith(prefix)
    assert ctx.budget.usage.tool_calls == 9


def test_nested_registry_calls_have_distinct_ids_and_outer_observation_matches(tmp_path):
    ctx = context(tmp_path)
    (tmp_path / "input.txt").write_text("visible")
    tools = registry()

    class Nested:
        name = "run_command"

        def run(self, context, command):
            return tools.call("read_file", context, path="input.txt")

    tools.register(Nested())
    gateway = ToolExecutionGateway(tools, ToolPermissionPolicy(tmp_path, ctx.validator))
    gateway.run_tool_calls(
        [{"tool_name": "run_command", "args": {"command": "echo nested"}}],
        {"task_id": "task-1", "allowed_tools": ["run_command"]},
        ctx,
    )
    calls = rows(ctx, "tool_calls.jsonl")
    assert len({r["tool_call_id"] for r in calls}) == len(calls) == 2
    assert calls[-1]["tool_call_id"] == rows(ctx, "tool_observations.jsonl")[0]["tool_call_id"]
    assert ctx.budget.usage.tool_calls == 2


def test_budget_refusal_keeps_its_identity_without_running_the_tool(tmp_path):
    ctx = context(tmp_path, limit=2)
    (tmp_path / "input.txt").write_text("visible")
    tools = registry()

    class Command:
        name = "run_command"

        def run(self, context, command):
            return ToolResult(ok=True, summary="Bounded command finished")

    tools.register(Command())
    gateway = ToolExecutionGateway(tools, ToolPermissionPolicy(tmp_path, ctx.validator))
    task = {"task_id": "task-1", "allowed_tools": ["run_command"]}
    gateway.run_tool_calls(
        [
            {"tool_name": "run_command", "args": {"command": "echo budget"}},
            {"tool_name": "run_command", "args": {"command": "echo budget"}},
        ],
        task,
        ctx,
        stop_on_failure=False,
    )
    calls = rows(ctx, "tool_calls.jsonl")
    observations = rows(ctx, "tool_observations.jsonl")
    assert [c["status"] for c in calls] == ["success", "denied"]
    assert len({c["tool_call_id"] for c in calls}) == 2
    assert [c["tool_call_id"] for c in calls] == [o["tool_call_id"] for o in observations]


def test_stopping_on_recorded_local_failure_does_not_emit_a_second_observation(tmp_path):
    ctx = context(tmp_path)
    gateway = ToolExecutionGateway(registry(), ToolPermissionPolicy(tmp_path, ctx.validator))
    with pytest.raises(RuntimeError, match="Tool failed"):
        gateway.run_tool_calls(
            [{"tool_name": "read_file", "args": {"path": "missing.txt"}}],
            {"task_id": "task-1", "allowed_tools": ["read_file"]},
            ctx,
        )
    calls = rows(ctx, "tool_calls.jsonl")
    observations = rows(ctx, "tool_observations.jsonl")
    assert len(calls) == len(observations) == 1
    assert calls[0]["tool_call_id"] == observations[0]["tool_call_id"]
