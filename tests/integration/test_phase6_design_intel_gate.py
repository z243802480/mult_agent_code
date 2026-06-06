from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.design_intel_contract import pilot_research_types
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

pytestmark = pytest.mark.workflow

GATE = json.loads(Path("benchmarks/phase6_design_intel_gate.json").read_text(encoding="utf-8"))


class DesignIntelFakeClient:
    def __init__(
        self,
        *,
        goal_type: str,
        normalized_goal: str,
        research_type: str | None = None,
        target_outputs: list[str] | None = None,
    ) -> None:
        self.goal_type = goal_type
        self.normalized_goal = normalized_goal
        self.research_type = research_type
        self.target_outputs = target_outputs or []
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        payload: dict = {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": request.messages[-1].content.split("\n", 1)[0],
            "normalized_goal": self.normalized_goal,
            "goal_type": self.goal_type,
            "assumptions": ["Fake provider design-intel pilot"],
            "constraints": ["local_first"],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": self.normalized_goal,
                    "source": "user",
                    "acceptance": ["Deliverable exists and is reviewable"],
                }
            ],
            "target_outputs": self.target_outputs,
            "definition_of_done": ["Artifact is complete"],
            "verification_strategy": ["manual_review"],
            "budget": {"max_iterations": 4, "max_model_calls": 20},
        }
        if self.research_type:
            payload["research_type"] = self.research_type
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


def _load_user_progress(run_dir: Path) -> list[dict]:
    path = run_dir / "user_progress.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_phase6_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    pilot = GATE["pilot_scope"]
    assert pilot["session_agent_default_unchanged"] is True
    assert set(pilot["research_types"]) == set(pilot_research_types())
    assert "documentation" in pilot["research_types"]


def test_documentation_plan_persists_research_type_and_user_progress(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    client = DesignIntelFakeClient(
        goal_type="report",
        normalized_goal="撰写 CLI 的 API 文档",
        target_outputs=["docs/README.md"],
    )
    result = PlanCommand(tmp_path, "撰写 CLI 的 API 文档", model_client=client).run()

    goal_spec = json.loads(result.goal_spec_path.read_text(encoding="utf-8"))
    assert goal_spec.get("research_type") == "documentation"

    task_plan = json.loads(result.task_plan_path.read_text(encoding="utf-8"))
    assert task_plan["tasks"]
    assert all(task.get("research_type") == "documentation" for task in task_plan["tasks"])

    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    progress = _load_user_progress(run_dir)
    assert any(
        event.get("data", {}).get("research_type") == "documentation"
        for event in progress
        if event.get("title") == "Task plan built"
    )
    plan_events = [
        event
        for event in progress
        if event.get("transcript_kind") == "plan" and event.get("display_level") == "main"
    ]
    assert plan_events[-1]["data"].get("research_type") == "documentation"


def test_creative_plan_persists_research_type(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    client = DesignIntelFakeClient(
        goal_type="unknown",
        normalized_goal="Brainstorm creative onboarding UI mockups",
        research_type="creative",
    )
    result = PlanCommand(
        tmp_path,
        "Brainstorm creative onboarding UI mockups",
        model_client=client,
    ).run()

    goal_spec = json.loads(result.goal_spec_path.read_text(encoding="utf-8"))
    assert goal_spec.get("research_type") == "creative"

    task_plan = json.loads(result.task_plan_path.read_text(encoding="utf-8"))
    assert all(task.get("research_type") == "creative" for task in task_plan["tasks"])
