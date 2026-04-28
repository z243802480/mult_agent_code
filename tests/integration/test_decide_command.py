import json
from pathlib import Path

from agent_runtime.commands.decide_command import DecideCommand
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
                    "original_goal": "choose an output surface",
                    "normalized_goal": "Choose an output surface",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Choose output surface",
                            "source": "user",
                            "acceptance": ["decision recorded"],
                        }
                    ],
                    "target_outputs": ["decision"],
                    "definition_of_done": ["decision recorded"],
                    "verification_strategy": ["inspect decision"],
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


def options_json() -> str:
    return json.dumps(
        [
            {"option_id": "web", "label": "Web UI", "tradeoff": "best interaction, higher scope"},
            {
                "option_id": "pdf",
                "label": "PDF Report",
                "tradeoff": "easy to share, less interactive",
            },
        ]
    )


def test_decide_command_creates_lists_and_resolves_decision(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "choose an output surface", model_client=FakePlanClient()).run()

    created = DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        question="Should the first output be a web UI or PDF?",
        options_json=options_json(),
        recommended_option_id="web",
        default_option_id="pdf",
        impact_json=json.dumps(
            {"scope": "medium", "budget": "medium", "risk": "low", "quality": "high"}
        ),
    ).run()

    assert created.action == "create"
    decision = created.decisions[0]
    assert decision["status"] == "pending"
    assert decision["decision_id"] == "decision-0001"
    assert decision["options"][0]["action"] == "create_task"
    assert decision["options"][1]["action"] == "create_task"

    pending = DecideCommand(tmp_path, run_id=plan.run_id, list_pending=True).run()
    assert len(pending.decisions) == 1

    resolved = DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        decision_id="decision-0001",
        select_option_id="web",
    ).run()

    assert resolved.decisions[0]["status"] == "resolved"
    assert resolved.decisions[0]["selected_option_id"] == "web"

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    decisions = (run_dir / "decisions.jsonl").read_text(encoding="utf-8")
    assert "decision-0001" in decisions
    assert "resolved" in decisions
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "decision_created" in events
    assert "decision_resolved" in events
    cost = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost["user_decisions"] == 2


def test_decide_command_can_use_default(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "choose an output surface", model_client=FakePlanClient()).run()
    DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        question="Which output should be default?",
        options_json=options_json(),
        default_option_id="pdf",
    ).run()

    result = DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        decision_id="decision-0001",
        use_default=True,
    ).run()

    assert result.decisions[0]["status"] == "defaulted"
    assert result.decisions[0]["selected_option_id"] == "pdf"
