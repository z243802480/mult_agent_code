import json
from pathlib import Path
import subprocess
import sys

import pytest

from asteria_runtime.core.budget import BudgetController, BudgetExceededError
from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.skill_adapter import SkillAdapter
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.models.base import ChatMessage, ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.tools.registry import ToolRegistry


def setup(root, model_limit=100):
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    policy = {"permission_mode": "reviewed_auto", "permissions": {"allow_network": True}, "protected_paths": [],
              "budgets": {"max_model_calls_per_goal": model_limit, "max_tool_calls_per_goal": 100}}
    run = root / ".asteria/runs/run-recovery"
    budget = BudgetController(policy, run.name)
    JsonStore(validator).write(run / "cost_report.json", budget.cost_report(), "cost_report")
    return validator, policy, run, budget


def request():
    return ChatRequest(purpose="task_execution", model_tier="strong",
                       messages=[ChatMessage(role="user", content="Continue")],
                       metadata={"run_id": "run-recovery"})


class Client:
    def chat(self, request):
        return ChatResponse(content="done", finish_reason="stop", usage=TokenUsage(10, 5, 15),
                            model_provider="fake", model_name="offline", raw_response={})


def test_recovery_joins_charged_channels_without_charging_a_gateway_refusal(tmp_path):
    validator, policy, run, budget = setup(tmp_path)
    client = MeteredModelClient(Client(), budget, ModelCallLogger(run, validator))
    client.chat(request())
    client.chat(request())
    (tmp_path / "input.txt").write_text("input")
    tools = ToolRegistry()
    tools.register(ReadFileTool())
    ctx = RuntimeContext(tmp_path, run.name, policy, validator, budget=budget)
    tools.call("read_file", ctx, path="input.txt")
    tools.call("unknown", ctx)

    class Skill:
        def invoke(self, request):
            return {"ok": True, "summary": "loaded"}

    class Session:
        def call(self, method, params):
            return {"isError": True, "content": []}

    gateway = ToolExecutionGateway(tools, ToolPermissionPolicy(tmp_path, validator),
        skill_adapter=SkillAdapter({"helper": Skill()}), mcp_adapter=McpAdapter({"server": Session()}))
    task = {"task_id": "task-1", "task_kind": "implementation", "risk": "medium",
            "allowed_tools": ["other"], "allowed_skills": ["helper"], "allowed_mcp": ["server"]}
    with pytest.raises(PermissionError):
        gateway.run_tool_calls([{"tool_name": "read_file", "args": {"path": "input.txt"}}], task, ctx)
    gateway.run_tool_calls([
        {"tool_name": "skill__helper", "args": {}}, {"tool_name": "mcp__server__echo", "args": {}}],
        task, ctx, stop_on_failure=False)
    assert budget.usage.tool_calls == 4
    prefix = {p.name: p.read_bytes() for p in run.glob("*.jsonl")}
    recovered = BudgetController.from_run(policy, run, validator)
    report = recovered.cost_report()
    assert report["model_calls"] == 2 and report["strong_model_calls"] == 2
    assert report["estimated_input_tokens"] == 20 and report["estimated_output_tokens"] == 10
    assert report["tool_calls"] == 4 and report["tool_budget_units"] == 7
    assert report["tool_call_breakdown"] == {"external": 2, "read_only": 1, "unknown": 1}
    assert BudgetController.from_run(policy, run, validator).cost_report() == report
    assert all((run / name).read_bytes() == value for name, value in prefix.items())


def test_process_exit_preserves_reservations_and_budget_refusal(tmp_path):
    validator, policy, run, _ = setup(tmp_path, model_limit=1)
    source = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import os,sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from asteria_runtime.core.budget import BudgetController;"
        "from asteria_runtime.storage.schema_validator import SchemaValidator;"
        "b=BudgetController.from_run(json.loads(sys.argv[4]),Path(sys.argv[2]),SchemaValidator(Path(sys.argv[3])));"
        "b.record_model_call('strong');b.record_tool_call('run_tests');os._exit(0)"
    )
    completed = subprocess.run([sys.executable, "-c", code, str(source), str(run),
        str(source.parent / "schemas"), json.dumps(policy)], capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    saved = JsonStore(validator).read(run / "cost_report.json", "cost_report")
    assert saved["model_calls"] == saved["tool_calls"] == 1
    recovered = BudgetController.from_run(policy, run, validator)
    metadata = recovered.cost_report()["accounting_recovery"]
    assert metadata["unrecorded_model_attempts"] == metadata["unrecorded_tool_attempts"] == 1
    assert metadata["precision"] == "conservative"
    with pytest.raises(BudgetExceededError):
        recovered.record_model_call("strong")
    assert JsonStore(validator).read(run / "cost_report.json", "cost_report")["model_calls"] == 2


def test_legacy_denial_is_conservative_and_does_not_rewrite_history(tmp_path):
    validator, policy, run, _ = setup(tmp_path)
    row = {"schema_version": "0.1.0", "run_id": run.name, "tool_call_id": "toolcall-0001",
           "tool_name": "write_file", "input_summary": "{}", "output_summary": "denied", "status": "denied"}
    JsonlStore(validator).append(run / "tool_calls.jsonl", row, "tool_call")
    raw = (run / "tool_calls.jsonl").read_bytes()
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["tool_calls"] == 1 and report["tool_budget_units"] == 2
    assert report["accounting_recovery"]["ambiguous_tool_attempts"] == 1
    assert report["accounting_recovery"]["precision"] == "conservative"
    assert (run / "tool_calls.jsonl").read_bytes() == raw


def test_unknown_model_usage_does_not_become_a_known_zero(tmp_path):
    validator, policy, run, _ = setup(tmp_path)
    ModelCallLogger(run, validator).record_failure(request(), "fake", "offline", "strong", "lost connection")
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == 1
    assert report["estimated_input_tokens"] is report["estimated_output_tokens"] is None
    assert report["accounting_recovery"]["unknown_usage_records"] == 1


def test_malformed_ledger_cannot_reset_or_overwrite_budget(tmp_path):
    validator, policy, run, _ = setup(tmp_path)
    raw = (run / "cost_report.json").read_bytes()
    (run / "model_calls.jsonl").write_text("not JSON\n")
    with pytest.raises(ValueError, match="invalid JSONL"):
        BudgetController.from_run(policy, run, validator)
    assert (run / "cost_report.json").read_bytes() == raw
