import json
from pathlib import Path

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
                    "original_goal": "做一个密码测试工具",
                    "normalized_goal": "构建本地优先密码测试工具",
                    "goal_type": "software_tool",
                    "assumptions": ["用户希望本地运行"],
                    "constraints": ["local_first", "privacy_safe"],
                    "non_goals": ["不证明密码绝对安全"],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "提供密码强度评分",
                            "source": "inferred",
                            "acceptance": ["输入密码后显示评分"],
                        },
                        {
                            "id": "req-0002",
                            "priority": "should",
                            "description": "提供隐私说明",
                            "source": "inferred",
                            "acceptance": ["说明密码不会发送到外部服务"],
                        },
                    ],
                    "target_outputs": ["local_cli", "readme", "tests"],
                    "definition_of_done": ["可以运行", "有测试"],
                    "verification_strategy": ["unit_tests"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


def test_plan_command_creates_run_goal_spec_tasks_and_logs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    assert result.task_count == 2
    assert result.goal_spec_path.exists()
    assert result.task_plan_path.exists()
    assert result.cost_report_path.exists()

    task_plan = json.loads(result.task_plan_path.read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "ready"
    assert task_plan["tasks"][1]["depends_on"] == ["task-0001"]

    run_dir = tmp_path / ".agent" / "runs" / result.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) >= 4

    backlog = json.loads((tmp_path / ".agent" / "tasks" / "backlog.json").read_text(encoding="utf-8"))
    assert len(backlog["tasks"]) == 2
