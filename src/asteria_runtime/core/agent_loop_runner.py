from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import (
    persist_agent_loop_decision,
    validate_agent_loop_decision,
)
from asteria_runtime.core.agent_loop_executor import persist_agent_loop_execution_result
from asteria_runtime.core.agent_loop_observation import (
    persist_agent_loop_observation_for_execution,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


DecisionProvider = Callable[[dict[str, Any], int], dict[str, Any] | None]


@dataclass(frozen=True)
class AgentLoopRound:
    decision: dict[str, Any]
    execution_result: dict[str, Any]
    observation: dict[str, Any]


class AgentLoopRunner:
    """Minimal persisted agent loop runner.

    It intentionally reuses the existing decision and execution result contracts.
    The provider receives the latest observation and returns the next model-owned
    AgentLoopDecision, allowing tests and future runtime integrations to drive
    multi-round loops without introducing a second execution kernel.
    """

    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator

    def run(
        self,
        *,
        run_dir: Path | None,
        initial_decision: dict[str, Any],
        decide_next: DecisionProvider,
        max_rounds: int = 2,
    ) -> list[AgentLoopRound]:
        if run_dir is None:
            return []
        if max_rounds < 1:
            return []
        rounds: list[AgentLoopRound] = []
        decision: dict[str, Any] | None = initial_decision
        for index in range(1, max_rounds + 1):
            if decision is None:
                break
            validate_agent_loop_decision(decision)
            persist_agent_loop_decision(
                run_dir=run_dir,
                validator=self.validator,
                decision=decision,
            )
            execution_result = persist_agent_loop_execution_result(
                run_dir=run_dir,
                validator=self.validator,
                decision=decision,
                create_decision_point=True,
            )
            if not isinstance(execution_result, dict):
                break
            observation = persist_agent_loop_observation_for_execution(
                run_dir=run_dir,
                validator=self.validator,
                execution_result=execution_result,
            )
            if not isinstance(observation, dict):
                break
            rounds.append(
                AgentLoopRound(
                    decision=decision,
                    execution_result=execution_result,
                    observation=observation,
                )
            )
            action = str(((decision.get("next_action") or {}).get("action")) or "")
            if action in {"ask", "stop"}:
                break
            decision = decide_next(observation, index)
        return rounds
