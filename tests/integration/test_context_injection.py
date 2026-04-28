import json
from pathlib import Path

from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


def _response(payload: dict) -> ChatResponse:
    return ChatResponse(
        content=json.dumps(payload, ensure_ascii=False),
        finish_reason="stop",
        usage=TokenUsage(1, 1, 2),
        model_provider="fake",
        model_name="fake-context",
        raw_response={},
    )


def _write_memory(root: Path, content: str) -> None:
    memory_path = root / ".agent" / "memory" / "decisions.jsonl"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory = {
        "schema_version": "0.1.0",
        "memory_id": "memory-0001",
        "type": "project_decision",
        "content": content,
        "source": {"decision_id": "decision-0001"},
        "tags": ["decision"],
        "confidence": 1.0,
        "created_at": "2026-04-28T10:00:00+08:00",
    }
    memory_path.write_text(json.dumps(memory, ensure_ascii=False) + "\n", encoding="utf-8")


class ContextPlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert "Keep outputs local and markdown-first" in request.messages[-1].content
        return _response(
            {
                "schema_version": "0.1.0",
                "goal_id": "goal-0001",
                "original_goal": "create context aware artifact",
                "normalized_goal": "Create context aware artifact",
                "goal_type": "software_tool",
                "assumptions": [],
                "constraints": ["local_first"],
                "non_goals": [],
                "expanded_requirements": [
                    {
                        "id": "req-0001",
                        "priority": "must",
                        "description": "Create a context aware artifact",
                        "source": "user",
                        "acceptance": ["artifact exists"],
                    }
                ],
                "target_outputs": ["markdown_report"],
                "definition_of_done": ["artifact exists"],
                "verification_strategy": ["inspect file"],
                "budget": {"max_iterations": 8, "max_model_calls": 60},
            }
        )


class ContextExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert "Keep outputs local and markdown-first" in request.messages[-1].content
        task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
        return _response(
            {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Create markdown artifact.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                        "reason": "create artifact",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -c \"from pathlib import Path; assert Path('CONTEXT.md').exists()\""
                        },
                        "reason": "verify artifact",
                    }
                ],
                "completion_notes": "CONTEXT.md exists",
            }
        )


class BrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
        return _response(
            {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Create broken artifact.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "broken.py", "content": "VALUE = 1\n", "overwrite": True},
                        "reason": "create artifact",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {"command": "python -c \"from broken import VALUE; assert VALUE == 2\""},
                        "reason": "verify artifact",
                    }
                ],
                "completion_notes": "intentionally broken",
            }
        )


class ContextDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert "Keep outputs local and markdown-first" in request.messages[-1].content
        task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
        return _response(
            {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Repair artifact.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "broken.py", "content": "VALUE = 2\n", "overwrite": True},
                        "reason": "repair artifact",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {"command": "python -c \"from broken import VALUE; assert VALUE == 2\""},
                        "reason": "verify repair",
                    }
                ],
                "completion_notes": "broken.py repaired",
            }
        )


def test_runtime_context_reaches_plan_execute_and_debug_agents(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_memory(tmp_path, "Keep outputs local and markdown-first")

    plan = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=ContextPlanClient(),
    ).run()
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert "1 memory entry" in task_plan["tasks"][0]["notes"]

    execute = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ContextExecuteClient(),
    ).run()
    assert execute.completed == 1

    plan_for_debug = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=ContextPlanClient(),
    ).run()
    blocked = ExecuteCommand(
        tmp_path,
        run_id=plan_for_debug.run_id,
        model_client=BrokenExecuteClient(),
    ).run()
    assert blocked.blocked == 1

    repaired = DebugCommand(
        tmp_path,
        run_id=plan_for_debug.run_id,
        model_client=ContextDebugClient(),
    ).run()
    assert repaired.repaired == 1
