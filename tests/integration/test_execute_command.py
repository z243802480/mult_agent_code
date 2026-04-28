import json
from pathlib import Path

from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a tiny notes tool",
                    "normalized_goal": "Create a tiny notes tool",
                    "goal_type": "software_tool",
                    "assumptions": ["local files are acceptable"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Create a notes module with a simple add function",
                            "source": "inferred",
                            "acceptance": ["a module file exists"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["module exists"],
                    "verification_strategy": ["run a command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create notes module and verify Python can import it.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "verify the module behavior",
                        }
                    ],
                    "completion_notes": "notes_tool.py contains a working add_note function",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeDisallowedToolClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Try to use a disallowed tool.",
                    "tool_calls": [
                        {
                            "tool_name": "unknown_tool",
                            "args": {},
                            "reason": "should be rejected before registry execution",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-disallowed",
            raw_response={},
        )


class FakeFailingVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create a module but fail verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "broken_tool.py",
                                "content": "VALUE = 1\n",
                                "overwrite": True,
                            },
                            "reason": "create a file",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": "python -c \"raise SystemExit(1)\""},
                            "reason": "simulate failed verification",
                        }
                    ],
                    "completion_notes": "verification should fail",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-failing",
            raw_response={},
        )


def test_execute_command_runs_ready_task_and_updates_logs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert (tmp_path / "notes_tool.py").read_text(encoding="utf-8") == (
        "def add_note(notes, text):\n    return [*notes, text]\n"
    )

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "done"
    assert "working add_note" in task_plan["tasks"][0]["notes"]

    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "task_started" in events
    assert "task_completed" in events
    tool_calls = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert "write_file" in tool_calls
    assert "run_command" in tool_calls
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[0]["decision"] == "keep"
    assert experiments[0]["candidate"]["backup_ids"]
    assert experiments[0]["metrics_after"]["verification_pass_rate"] == 1.0
    artifacts = [
        json.loads(line)
        for line in (run_dir / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert artifacts[0]["path"] == "notes_tool.py"
    assert artifacts[0]["type"] == "source_file"

    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 2
    assert cost_report["tool_calls"] == 2
    assert cost_report["estimated_input_tokens"] == 25
    assert cost_report["estimated_output_tokens"] == 45


def test_execute_command_blocks_disallowed_tool_without_tool_call(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeDisallowedToolClient()).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "not allowed" in task_plan["tasks"][0]["notes"]
    assert not (run_dir / "tool_calls.jsonl").exists()


def test_execute_command_blocks_when_verification_fails(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeFailingVerificationClient()).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "broken_tool.py").exists()
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    tool_calls = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert "nonzero_exit" in tool_calls
    assert "restore_backup" in tool_calls
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[0]["decision"] == "discard"
    assert experiments[0]["metrics_after"]["verification_pass_rate"] == 0.0
    assert experiments[0]["candidate"]["rollback"][0]["restored"] == ["broken_tool.py"]
    assert not (run_dir / "artifacts.jsonl").exists()
