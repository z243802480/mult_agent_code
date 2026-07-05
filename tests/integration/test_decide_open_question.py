import json
from pathlib import Path

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "build a small tool",
                    "normalized_goal": "Build a small tool",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Build a small tool",
                            "source": "user",
                            "acceptance": ["tool exists"],
                        }
                    ],
                    "target_outputs": ["tool"],
                    "definition_of_done": ["tool exists"],
                    "verification_strategy": ["inspect"],
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


def test_open_question_create_and_answer_roundtrip(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a small tool", model_client=FakePlanClient()).run()

    created = DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        question="Which database should the tool use?",
        open_question=True,
    ).run()

    decision = created.decisions[0]
    assert created.action == "create"
    assert decision["status"] == "pending"
    assert decision["options"] == []
    assert decision["metadata"]["kind"] == "open_question"
    assert decision["answer"] is None

    answered = DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        decision_id=decision["decision_id"],
        answer="Use SQLite — it's local-first and needs no server.",
    ).run()

    assert answered.action == "answer"
    assert answered.decisions[0]["status"] == "answered"
    assert "SQLite" in answered.decisions[0]["answer"]

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions_text = (run_dir / "decisions.jsonl").read_text(encoding="utf-8")
    assert "answered" in decisions_text
    assert "SQLite" in decisions_text


def test_resume_folds_answer_into_a_guidance_task(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    resume = ResumeCommand(tmp_path)

    decision = {
        "schema_version": "0.1.0",
        "decision_id": "decision-0001",
        "status": "answered",
        "question": "Which database should the tool use?",
        "recommended_option_id": "",
        "options": [],
        "default_option_id": "",
        "impact": {"scope": "low", "budget": "low", "risk": "low", "quality": "medium"},
        "selected_option_id": None,
        "answer": "Use SQLite — it's local-first.",
        "created_at": "2026-07-05T00:00:00Z",
        "metadata": {"kind": "open_question"},
        "resolved_at": "2026-07-05T00:01:00Z",
    }
    task_plan: dict = {"tasks": []}

    result = resume._apply_open_question_answer(decision, task_plan, "run-0001")

    assert result is not None
    effect, guidance_task = result
    assert effect == "open_question_answer_applied"
    assert guidance_task is not None
    assert guidance_task in task_plan["tasks"]
    # The answer is authoritative guidance the loop will pick up next iteration.
    assert "SQLite" in guidance_task["description"]
    assert "Which database" in guidance_task["description"]
    assert guidance_task["status"] == "ready"


def test_resume_open_question_without_answer_is_recorded_not_tasked(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    resume = ResumeCommand(tmp_path)
    decision = {
        "metadata": {"kind": "open_question"},
        "answer": "   ",
        "decision_id": "decision-0002",
        "question": "q?",
        "impact": {},
    }
    task_plan: dict = {"tasks": []}

    result = resume._apply_open_question_answer(decision, task_plan, "run-0001")

    assert result == ("open_question_empty_answer", None)
    assert task_plan["tasks"] == []
