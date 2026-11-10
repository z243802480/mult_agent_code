"""Keep the frozen S108 behavioral oracle in normal CI without duplicating its assertions."""
from pathlib import Path
import subprocess
import sys


def test_frozen_tool_batch_behavioral_oracle() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "benchmarks/dogfood/tool_batch_oracle.py.txt")],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_runtime_wrapper_preserves_prefix_and_does_not_spawn_after_denial(tmp_path):
    from asteria_runtime.commands.execute_command import _SubagentAwareToolRunner
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from tests.unit.test_tool_execution_gateway import _gateway

    gateway, context = _gateway(tmp_path)
    spawned = []
    runner = _SubagentAwareToolRunner(gateway, lambda args: spawned.append(args))
    calls = [
        {"tool_name": "read_file", "args": {"path": "first.txt"}},
        {"tool_name": "write_file", "args": {"path": "denied.txt"}},
        {"tool_name": "spawn_subagent", "args": {"task": "must not launch"}},
    ]
    observations = execute_tool_calls(runner, calls, {"task_id": "task-1", "allowed_tools": ["read_file"]}, context)
    assert [(o.tool_name, o.ok) for o in observations] == [("read_file", True), ("write_file", False)]
    assert not spawned
    assert observations[-1].data["unexecuted_tools"] == ["spawn_subagent"]


def test_adjacent_expert_fanout_keeps_its_batch_and_call_order(tmp_path):
    from asteria_runtime.commands.execute_command import _SubagentAwareToolRunner
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from tests.unit.test_tool_execution_gateway import _gateway, FakeResult

    gateway, context = _gateway(tmp_path)
    batches = []
    def fanout(args):
        batches.append(args)
        return [FakeResult(ok=True, summary=a["task"]) for a in args]
    runner = _SubagentAwareToolRunner(gateway, lambda args: None, spawn_batch=fanout)
    calls = [
        {"tool_name": "read_file", "args": {"path": "first.txt"}},
        {"tool_name": "spawn_subagent", "args": {"task": "A"}},
        {"tool_name": "spawn_subagent", "args": {"task": "B"}},
        {"tool_name": "read_file", "args": {"path": "last.txt"}},
    ]
    observations = execute_tool_calls(runner, calls, {"task_id": "task-1", "allowed_tools": ["read_file"]}, context)
    assert [o.tool_name for o in observations] == ["read_file", "spawn_subagent", "spawn_subagent", "read_file"]
    assert [o.summary for o in observations[1:3]] == ["A", "B"]
    assert len(batches) == 1 and len(batches[0]) == 2


def test_alias_provenance_matches_canonical_persisted_observation(tmp_path):
    import json
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from tests.unit.test_tool_execution_gateway import _gateway

    gateway, context = _gateway(tmp_path)
    observations = execute_tool_calls(gateway, [{"tool_name": "grep", "args": {"pattern": "x", "path": "."}}],
                                      {"task_id": "task-1", "allowed_tools": ["search_text"]}, context)
    assert observations[0].tool_name == "search_text"
    assert observations[0].data["model_tool_name"] == "grep"
    evidence = json.loads((tmp_path / "tool_observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert evidence["observation"]["data"]["model_tool_name"] == "grep"


def test_unexpected_adapter_failures_are_also_persisted(tmp_path):
    import json
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
    from tests.unit.test_tool_execution_gateway import _gateway

    class BrokenAdapter:
        def invoke_tool(self, **kwargs):
            raise RuntimeError("unexpected MCP exception")
        def invoke(self, **kwargs):
            raise RuntimeError("unexpected skill exception")
    for name in ["mcp__demo__echo", "skill__demo"]:
        root = tmp_path / name
        gateway, context = _gateway(root)
        gateway = ToolExecutionGateway(gateway.registry, gateway.permission_policy,
                                       mcp_adapter=BrokenAdapter(), skill_adapter=BrokenAdapter())
        observations = execute_tool_calls(gateway, [
            {"tool_name": "read_file", "args": {"path": "prefix.txt"}},
            {"tool_name": name, "args": {}},
        ], {"task_id": "task-1", "allowed_tools": ["read_file"]}, context)
        evidence = [json.loads(line) for line in (root / "tool_observations.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [(o.tool_name, o.ok) for o in observations] == [("read_file", True), (name, False)]
        assert [(o["tool_name"], o["ok"]) for o in evidence] == [("read_file", True), (name, False)]


def test_short_result_list_never_silently_reports_a_complete_batch():
    from asteria_runtime.core.model_driven_turn import execute_tool_calls
    from tests.unit.test_model_driven_turn import FakeToolRunner, FakeToolResult
    runner = FakeToolRunner([[FakeToolResult(summary="known prefix")]])
    observations = execute_tool_calls(runner, [
        {"tool_name": "read_file", "args": {}}, {"tool_name": "write_file", "args": {}},
    ], {}, object())
    assert observations[0].ok and observations[0].summary == "known prefix"
    assert observations[1].tool_name == "tool_batch" and not observations[1].ok
    assert "unknown" in observations[1].summary
