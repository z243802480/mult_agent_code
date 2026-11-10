import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from tests.integration.test_plan_command import FakePlanClient


class BudgetClient:
    def __init__(self):
        self.calls = 0

    def chat(self, request):
        self.calls += 1
        call = ({"tool_name": "write_file", "args": {
            "path": "src/notes_tool.py", "content": "must not execute"}}
            if self.calls == 4 else {"tool_name": "read_file", "args": {"path": "AGENTS.md"}})
        return ChatResponse(
            content=json.dumps({"narration": "inspect", "tool_calls": [call], "done": False}),
            finish_reason="stop", usage=TokenUsage(1, 1, 2), model_provider="fake",
            model_name="budget-test", raw_response={},
        )


def test_long_task_budget_stops_before_tools_and_creates_existing_decision(tmp_path: Path):
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria/runs" / plan.run_id
    policy_path = tmp_path / ".asteria/policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["active_budget_profile"] = ""
    policy["budgets"]["max_model_calls_per_goal"] = 4
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    cost_path = run_dir / "cost_report.json"
    report = json.loads(cost_path.read_text(encoding="utf-8"))
    report["model_calls"] = 0
    cost_path.write_text(json.dumps(report), encoding="utf-8")
    task_path = run_dir / "task_plan.json"
    board = json.loads(task_path.read_text(encoding="utf-8"))
    task = board["tasks"][0]
    task["verification_policy"]["command_source"] = "planner_task"
    task["validation_commands"] = [
        'python -c "from pathlib import Path; Path(\'should-not-run.txt\').write_text(\'bad\')"'
    ]
    task_path.write_text(json.dumps(board), encoding="utf-8")
    client = BudgetClient()
    command = RunCommand(tmp_path, "create a tiny notes tool", execute_model_client=client,
                         enable_research=False)
    steps = []
    command._execute_until_no_ready(plan.run_id, steps, 1)
    assert client.calls == 4
    assert not (tmp_path / "src/notes_tool.py").exists()
    assert not (tmp_path / "should-not-run.txt").exists()
    summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))
    assert summary["exit_reason"] == "budget_hard_stop"
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["status"] == "paused"
    decisions = [json.loads(line) for p in (tmp_path / ".asteria").rglob("decisions.jsonl")
                 for line in p.read_text(encoding="utf-8").splitlines()]
    assert any(d["status"] == "pending" and "budget" in json.dumps(d).lower() for d in decisions)
    assert not any(step.name == "replan" for step in steps)
    digest = run_dir / "task_progress" / (task["task_id"] + ".json")
    assert "read_file" in digest.read_text(encoding="utf-8")
