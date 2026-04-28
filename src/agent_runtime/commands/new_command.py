from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand, PlanResult
from agent_runtime.models.base import ModelClient


@dataclass(frozen=True)
class NewResult:
    plan_result: PlanResult

    @property
    def run_id(self) -> str:
        return self.plan_result.run_id

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Created new isolated run: {self.run_id}",
                f"GoalSpec: {self.plan_result.goal_spec_path}",
                f"Task plan: {self.plan_result.task_plan_path}",
                "Current run pointer updated.",
            ]
        )


class NewCommand:
    def __init__(
        self,
        root: Path,
        goal: str,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.goal = goal
        self.model_client = model_client

    def run(self) -> NewResult:
        if not (self.root / ".agent").exists():
            InitCommand(self.root).run()
        plan = PlanCommand(self.root, self.goal, model_client=self.model_client).run()
        return NewResult(plan)
