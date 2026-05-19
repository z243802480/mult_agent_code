from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class DeadlineBudget:
    """Derived timeout budget for one acceptance scenario or smoke run."""

    scenario_seconds: int
    model_max_retries: int = 1
    subprocess_grace_seconds: int = 30
    suite_seconds: int | None = None
    review_seconds_override: int | None = None
    provider_call_seconds_override: int | None = None

    @classmethod
    def for_scenario(
        cls,
        scenario_seconds: int,
        *,
        model_max_retries: int = 1,
        suite_seconds: int | None = None,
    ) -> "DeadlineBudget":
        return cls(
            scenario_seconds=max(60, int(scenario_seconds)),
            model_max_retries=max(0, int(model_max_retries)),
            suite_seconds=suite_seconds,
        )

    @classmethod
    def for_smoke(
        cls,
        command_timeout_seconds: int,
        *,
        model_max_retries: int = 1,
    ) -> "DeadlineBudget":
        return cls.for_scenario(
            command_timeout_seconds,
            model_max_retries=model_max_retries,
            suite_seconds=command_timeout_seconds,
        )

    @property
    def run_seconds(self) -> int:
        return max(60, self.scenario_seconds - self.subprocess_grace_seconds)

    @property
    def smoke_command_seconds(self) -> int:
        return self.run_seconds

    @property
    def subprocess_seconds(self) -> int:
        return self.scenario_seconds

    @property
    def review_seconds(self) -> int:
        if self.review_seconds_override is not None:
            return max(1, int(self.review_seconds_override))
        return min(90, max(30, self.scenario_seconds // 6))

    @property
    def recovery_seconds(self) -> int:
        return min(self.run_seconds, max(60, self.scenario_seconds // 3))

    @property
    def provider_call_seconds(self) -> int:
        if self.provider_call_seconds_override is not None:
            return max(1, int(self.provider_call_seconds_override))
        return min(90, max(30, self.scenario_seconds // 4))

    @property
    def cheap_provider_call_seconds(self) -> int:
        return min(45, self.provider_call_seconds)

    @property
    def stream_idle_timeout_seconds(self) -> int:
        return min(30, self.provider_call_seconds)

    def as_dict(self) -> dict[str, int | None]:
        return {
            "suite_seconds": self.suite_seconds,
            "scenario_seconds": self.scenario_seconds,
            "subprocess_seconds": self.subprocess_seconds,
            "run_seconds": self.run_seconds,
            "smoke_command_seconds": self.smoke_command_seconds,
            "review_seconds": self.review_seconds,
            "recovery_seconds": self.recovery_seconds,
            "provider_call_seconds": self.provider_call_seconds,
            "cheap_provider_call_seconds": self.cheap_provider_call_seconds,
            "stream_idle_timeout_seconds": self.stream_idle_timeout_seconds,
            "model_max_retries": self.model_max_retries,
        }


def apply_deadline_budget_env(env: MutableMapping[str, str], budget: DeadlineBudget) -> None:
    provider_timeout = str(budget.provider_call_seconds)
    cheap_timeout = str(budget.cheap_provider_call_seconds)
    stream_idle = str(budget.stream_idle_timeout_seconds)
    for name in (
        "AGENT_MODEL_TIMEOUT_SECONDS",
        "AGENT_MODEL_STRONG_TIMEOUT_SECONDS",
        "AGENT_MODEL_MEDIUM_TIMEOUT_SECONDS",
    ):
        env.setdefault(name, provider_timeout)
    env.setdefault("AGENT_MODEL_CHEAP_TIMEOUT_SECONDS", cheap_timeout)
    for name in (
        "AGENT_MODEL_STREAM_IDLE_TIMEOUT_SECONDS",
        "AGENT_MODEL_STRONG_STREAM_IDLE_TIMEOUT_SECONDS",
        "AGENT_MODEL_MEDIUM_STREAM_IDLE_TIMEOUT_SECONDS",
        "AGENT_MODEL_CHEAP_STREAM_IDLE_TIMEOUT_SECONDS",
    ):
        env.setdefault(name, stream_idle)
    for name in (
        "AGENT_MODEL_MAX_RETRIES",
        "AGENT_MODEL_STRONG_MAX_RETRIES",
        "AGENT_MODEL_MEDIUM_MAX_RETRIES",
        "AGENT_MODEL_CHEAP_MAX_RETRIES",
    ):
        env.setdefault(name, str(budget.model_max_retries))
    env.setdefault("AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS", str(budget.run_seconds))
    env.setdefault("AGENT_MODEL_SMOKE_REVIEW_TIMEOUT_SECONDS", str(budget.review_seconds))
    env.setdefault("AGENT_MODEL_SMOKE_RECOVERY_TIMEOUT_SECONDS", str(budget.recovery_seconds))


apply_timeout_budget_env = apply_deadline_budget_env
