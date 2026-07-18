import json
from pathlib import Path

import pytest

from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from tests.helpers.spine import spine_response

pytestmark = pytest.mark.spine_default


def _mount_present(request: ChatRequest, needle: str) -> bool:
    return any(needle in message.content for message in request.messages)


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
    memory_path = root / ".asteria" / "memory" / "decisions.jsonl"
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
                "target_outputs": ["CONTEXT.md"],
                "definition_of_done": ["artifact exists"],
                "verification_strategy": ["inspect file"],
                "budget": {"max_iterations": 8, "max_model_calls": 60},
            }
        )


class ContextExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert _mount_present(request, "Keep outputs local and markdown-first")
        return spine_response(
            request,
            narration="创建 markdown 产物并验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": "python -c \"from pathlib import Path; assert Path('CONTEXT.md').exists()\""
                    },
                },
            ],
            model_name="fake-context",
        )


class BrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="写入(会验证失败的)产物。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "remote\n", "overwrite": True},
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            'python -c "from pathlib import Path; '
                            "assert Path('CONTEXT.md').read_text(encoding='utf-8') == 'local\\n'\""
                        )
                    },
                },
            ],
            model_name="fake-context",
        )


class ContextDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert _mount_present(request, "Keep outputs local and markdown-first")
        return spine_response(
            request,
            narration="修复产物并验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            'python -c "from pathlib import Path; '
                            "assert Path('CONTEXT.md').read_text(encoding='utf-8') == 'local\\n'\""
                        )
                    },
                },
            ],
            model_name="fake-context",
        )


def test_runtime_context_reaches_plan_execute_and_debug_agents(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_memory(tmp_path, "Keep outputs local and markdown-first")

    plan = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=ContextPlanClient(),
    ).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
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


class MemoryLoopPlanClient:
    """Same goal-spec payload as ContextPlanClient, minus its decisions.jsonl mount assertion —
    this scenario seeds no harness memory; the model writes its own."""

    def chat(self, request: ChatRequest) -> ChatResponse:
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
                "target_outputs": ["CONTEXT.md"],
                "definition_of_done": ["artifact exists"],
                "verification_strategy": ["inspect file"],
                "budget": {"max_iterations": 8, "max_model_calls": 60},
            }
        )


class RememberingExecuteClient:
    """Turn 1 writes the artifact AND remembers a durable lesson via the memory channel."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="创建产物并沉淀教训。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                },
                {
                    "tool_name": "remember",
                    "args": {
                        "content": "This workspace requires markdown-first local outputs.",
                        "type": "project_decision",
                        "tags": ["convention"],
                        "confidence": 0.9,
                    },
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": "python -c \"from pathlib import Path; assert Path('CONTEXT.md').exists()\""
                    },
                },
            ],
            model_name="fake-context",
        )


class RecallCheckExecuteClient:
    """A LATER run: asserts the previous run's remembered lesson reaches its prompt via the
    memory index, then recalls it in full through recall_memory."""

    def __init__(self) -> None:
        self.saw_memory_index = False

    def chat(self, request: ChatRequest) -> ChatResponse:
        if _mount_present(request, "requires markdown-first local outputs"):
            self.saw_memory_index = True
        return spine_response(
            request,
            narration="读回记忆并产出。",
            tool_calls=[
                {"tool_name": "recall_memory", "args": {"memory_id": "note-0001"}},
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": "python -c \"from pathlib import Path; assert Path('CONTEXT.md').exists()\""
                    },
                },
            ],
            model_name="fake-context",
        )


def test_model_remembered_lesson_survives_into_next_runs_prompt(tmp_path: Path) -> None:
    # The full memory loop on the real execute path: run 1's model calls `remember` (planner
    # contract -> capability gate -> gateway -> tool), the entry lands schema-valid in
    # .asteria/memory/model_notes.jsonl, and run 2's prompt carries it in the memory index —
    # cross-run memory written by the model itself, not the harness.
    InitCommand(tmp_path).run()

    plan = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=MemoryLoopPlanClient(),
    ).run()
    execute = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=RememberingExecuteClient(),
    ).run()
    assert execute.completed == 1

    notes = tmp_path / ".asteria" / "memory" / "model_notes.jsonl"
    rows = [
        json.loads(line) for line in notes.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["memory_id"] == "note-0001"
    assert rows[0]["source"]["kind"] == "model"
    assert rows[0]["source"]["run_id"] == plan.run_id

    second_plan = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=MemoryLoopPlanClient(),
    ).run()
    recall_client = RecallCheckExecuteClient()
    second = ExecuteCommand(
        tmp_path,
        run_id=second_plan.run_id,
        model_client=recall_client,
    ).run()
    assert second.completed == 1
    assert recall_client.saw_memory_index, "run 2's prompt must carry the remembered lesson"

    observations = [
        json.loads(line)
        for line in (
            tmp_path / ".asteria" / "runs" / second_plan.run_id / "tool_observations.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    recall_obs = [item for item in observations if item["tool_name"] == "recall_memory"]
    assert recall_obs and recall_obs[0]["ok"] is True


class PressureAwareExecuteClient:
    """断言 near_limit 压力下 grounding 里文件摘录被瘦掉：路径清单仍在、内容不在、带说明。"""

    def __init__(self) -> None:
        self.saw_slimmed_grounding = False

    def chat(self, request: ChatRequest) -> ChatResponse:
        joined = "\n".join(str(m.content) for m in request.messages)
        if (
            "content_elided_under_context_pressure" in joined
            and "UNIQUE_EXCERPT_MARKER" not in joined
            and "marker_module.py" in joined
        ):
            self.saw_slimmed_grounding = True
        return spine_response(
            request,
            narration="压力下产出。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {"path": "CONTEXT.md", "content": "local\n", "overwrite": True},
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": "python -c \"from pathlib import Path; assert Path('CONTEXT.md').exists()\""
                    },
                },
            ],
            model_name="fake-context",
        )


def test_context_pressure_slims_workspace_excerpts_from_execute_grounding(tmp_path: Path) -> None:
    # S90 压缩真缩（主路径）：预算压力 near_limit 时，本该整段进 prompt 的 workspace_files
    # 内容摘录被真的从 grounding 里去掉（只剩路径清单 + 说明），而不是只写快照记账。
    InitCommand(tmp_path).run()
    (tmp_path / "marker_module.py").write_text(
        "UNIQUE_EXCERPT_MARKER = 'should not ride the prompt under pressure'\n",
        encoding="utf-8",
    )

    plan = PlanCommand(
        tmp_path,
        "create context aware artifact",
        model_client=MemoryLoopPlanClient(),
    ).run()

    cost_path = tmp_path / ".asteria" / "runs" / plan.run_id / "cost_report.json"
    report = json.loads(cost_path.read_text(encoding="utf-8"))
    report["context_pressure_status"] = "near_limit"
    report["context_window_ratio"] = 0.8
    cost_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    client = PressureAwareExecuteClient()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert execute.completed == 1
    assert client.saw_slimmed_grounding, (
        "near_limit 下 execute 的 grounding 必须瘦身：路径在、摘录不在、带 elision 说明"
    )
    # 1.2.137: the slimmed seed itself is never persisted, so the slim action must leave a
    # durable diagnostic event — otherwise live runs cannot prove the mechanism fired.
    progress_path = tmp_path / ".asteria" / "runs" / plan.run_id / "user_progress.jsonl"
    events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    slim_events = [e for e in events if e.get("title") == "Context pressure: grounding slimmed"]
    assert slim_events, "slim 动作必须留 diagnostic 事件"
    assert slim_events[0]["data"]["context_pressure_status"] == "near_limit"
