import json
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
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
                    "original_goal": "build a password test tool",
                    "normalized_goal": "Build a local-first password test tool",
                    "goal_type": "software_tool",
                    "assumptions": ["runs locally"],
                    "constraints": ["privacy_safe"],
                    "non_goals": ["does not prove absolute security"],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Provide password strength scoring",
                            "source": "inferred",
                            "acceptance": ["shows a score after password input"],
                        }
                    ],
                    "target_outputs": ["local_cli"],
                    "definition_of_done": ["can run locally"],
                    "verification_strategy": ["unit_tests"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake",
            raw_response={},
        )


def test_compact_command_creates_snapshot_from_latest_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()

    compact = CompactCommand(tmp_path, focus="test handoff").run()

    assert compact.run_id == plan.run_id
    assert compact.snapshot_path.exists()
    snapshot = json.loads(compact.snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["goal_summary"] == "Build a local-first password test tool"
    assert snapshot["definition_of_done"] == ["can run locally"]
    assert snapshot["active_tasks"] == ["task-0001"]

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "context_compacted" in events
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 1
    assert cost_report["context_compactions"] == 1
