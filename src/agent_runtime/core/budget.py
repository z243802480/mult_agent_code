from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class BudgetUsage:
    model_calls: int = 0
    tool_calls: int = 0
    repair_attempts: int = 0
    research_calls: int = 0
    user_decisions: int = 0
    context_compactions: int = 0
    estimated_input_tokens: int | None = 0
    estimated_output_tokens: int | None = 0
    strong_model_calls: int = 0
    cheap_model_calls: int = 0
    warnings: list[str] = field(default_factory=list)


class BudgetController:
    def __init__(self, policy: dict, run_id: str | None = None) -> None:
        self.policy = policy
        self.run_id = run_id
        self.usage = BudgetUsage()

    @classmethod
    def from_report(
        cls, policy: dict, report: dict, run_id: str | None = None
    ) -> "BudgetController":
        controller = cls(policy, run_id=run_id or report.get("run_id"))
        controller.usage.model_calls = int(report.get("model_calls", 0))
        controller.usage.tool_calls = int(report.get("tool_calls", 0))
        controller.usage.repair_attempts = int(report.get("repair_attempts", 0))
        controller.usage.context_compactions = int(report.get("context_compactions", 0))
        controller.usage.user_decisions = int(report.get("user_decisions", 0))
        controller.usage.estimated_input_tokens = report.get("estimated_input_tokens")
        controller.usage.estimated_output_tokens = report.get("estimated_output_tokens")
        controller.usage.strong_model_calls = int(report.get("strong_model_calls", 0))
        controller.usage.cheap_model_calls = int(report.get("cheap_model_calls", 0))
        controller.usage.warnings = list(report.get("warnings", []))
        return controller

    def record_model_call(
        self,
        model_tier: str = "medium",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self.usage.model_calls += 1
        if model_tier == "strong":
            self.usage.strong_model_calls += 1
        if model_tier == "cheap":
            self.usage.cheap_model_calls += 1
        self.record_model_tokens(input_tokens, output_tokens)
        self._check_limit("model_calls", self.usage.model_calls, "max_model_calls_per_goal")

    def record_model_tokens(
        self,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        if input_tokens is not None and self.usage.estimated_input_tokens is not None:
            self.usage.estimated_input_tokens += input_tokens
        elif input_tokens is not None:
            self.usage.estimated_input_tokens = None
        if output_tokens is not None and self.usage.estimated_output_tokens is not None:
            self.usage.estimated_output_tokens += output_tokens
        elif output_tokens is not None:
            self.usage.estimated_output_tokens = None

    def record_tool_call(self) -> None:
        self.usage.tool_calls += 1
        self._check_limit("tool_calls", self.usage.tool_calls, "max_tool_calls_per_goal")

    def record_repair_attempt(self) -> None:
        self.usage.repair_attempts += 1
        self._check_limit(
            "repair_attempts",
            self.usage.repair_attempts,
            "max_repair_attempts_total",
        )

    def record_research_call(self) -> None:
        self.usage.research_calls += 1
        self._check_limit("research_calls", self.usage.research_calls, "max_research_calls")

    def record_user_decision(self) -> None:
        self.usage.user_decisions += 1
        self._check_limit("user_decisions", self.usage.user_decisions, "max_user_decisions")

    def record_context_compaction(self) -> None:
        self.usage.context_compactions += 1

    def cost_report(self) -> dict:
        status = "within_budget"
        if self.usage.warnings:
            status = "near_limit"
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "model_calls": self.usage.model_calls,
            "tool_calls": self.usage.tool_calls,
            "estimated_input_tokens": self.usage.estimated_input_tokens,
            "estimated_output_tokens": self.usage.estimated_output_tokens,
            "strong_model_calls": self.usage.strong_model_calls,
            "cheap_model_calls": self.usage.cheap_model_calls,
            "repair_attempts": self.usage.repair_attempts,
            "research_calls": self.usage.research_calls,
            "context_compactions": self.usage.context_compactions,
            "user_decisions": self.usage.user_decisions,
            "status": status,
            "warnings": self.usage.warnings,
        }

    @staticmethod
    def pressure(policy: dict, report: dict) -> dict:
        budgets = policy["budgets"]
        ratios: dict[str, float] = {
            "model_calls": _ratio(
                report.get("model_calls", 0), budgets["max_model_calls_per_goal"]
            ),
            "tool_calls": _ratio(report.get("tool_calls", 0), budgets["max_tool_calls_per_goal"]),
            "repair_attempts": _ratio(
                report.get("repair_attempts", 0),
                budgets["max_repair_attempts_total"],
            ),
            "research_calls": _ratio(
                report.get("research_calls", 0), budgets["max_research_calls"]
            ),
            "user_decisions": _ratio(
                report.get("user_decisions", 0), budgets["max_user_decisions"]
            ),
        }
        highest_label = max(ratios, key=lambda key: ratios[key])
        highest_ratio = ratios[highest_label]
        context = policy.get("context", {})
        compaction_threshold = float(context.get("compaction_threshold", 0.75))
        hard_stop_threshold = float(context.get("hard_stop_threshold", 0.9))
        if highest_ratio >= 1:
            status = "exceeded"
        elif highest_ratio >= hard_stop_threshold:
            status = "hard_stop"
        elif highest_ratio >= compaction_threshold:
            status = "near_limit"
        else:
            status = "within_budget"
        return {
            "status": status,
            "ratios": ratios,
            "highest_label": highest_label,
            "highest_ratio": highest_ratio,
        }

    def _check_limit(self, label: str, value: int, policy_key: str) -> None:
        limit = int(self.policy["budgets"][policy_key])
        if value > limit:
            raise BudgetExceededError(f"{label} exceeded budget: {value} > {limit}")
        if value >= max(1, int(limit * 0.8)):
            warning = f"{label} is near budget: {value}/{limit}"
            if warning not in self.usage.warnings:
                self.usage.warnings.append(warning)


def _ratio(value: object, limit: object) -> float:
    numeric_limit = max(1, _as_int(limit))
    return max(0, _as_int(value)) / numeric_limit


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return 0
