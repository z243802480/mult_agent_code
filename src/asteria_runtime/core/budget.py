from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from asteria_runtime.core.context_budget import ContextPressure, context_pressure


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class BudgetUsage:
    model_calls: int = 0
    tool_calls: int = 0
    tool_budget_units: int = 0
    tool_call_breakdown: dict[str, int] = field(default_factory=dict)
    repair_attempts: int = 0
    research_calls: int = 0
    user_decisions: int = 0
    context_compactions: int = 0
    estimated_input_tokens: int | None = 0
    estimated_output_tokens: int | None = 0
    latest_context_estimated_tokens: int = 0
    max_context_estimated_tokens: int = 0
    # Truth feedback (S90): the prompt token count the PROVIDER reported for the latest call, and
    # the running correction factor (observed/estimated EMA) applied to future char-heuristic
    # estimates. 1.0 until the first real usage arrives.
    latest_observed_prompt_tokens: int = 0
    context_estimate_calibration: float = 1.0
    context_window_tokens: int = 0
    context_window_ratio: float = 0.0
    context_pressure_status: str = "within_budget"
    latest_context_sections: dict[str, int] = field(default_factory=dict)
    max_context_sections: dict[str, int] = field(default_factory=dict)
    context_duplicate_content_hashes: list[str] = field(default_factory=list)
    strong_model_calls: int = 0
    cheap_model_calls: int = 0
    warnings: list[str] = field(default_factory=list)


class BudgetController:
    def __init__(self, policy: dict, run_id: str | None = None) -> None:
        self.policy = policy
        self.budgets = resolve_budget_limits(policy)
        self.run_id = run_id
        self.usage = BudgetUsage()
        self._lock = RLock()
        self._last_raw_context_estimate = 0

    @classmethod
    def from_report(
        cls, policy: dict, report: dict, run_id: str | None = None
    ) -> "BudgetController":
        controller = cls(policy, run_id=run_id or report.get("run_id"))
        controller.usage.model_calls = int(report.get("model_calls", 0))
        controller.usage.tool_calls = int(report.get("tool_calls", 0))
        controller.usage.tool_budget_units = int(
            report.get("tool_budget_units", report.get("tool_calls", 0))
        )
        raw_breakdown = report.get("tool_call_breakdown")
        if isinstance(raw_breakdown, dict):
            controller.usage.tool_call_breakdown = {
                str(key): int(value) for key, value in raw_breakdown.items()
            }
        controller.usage.repair_attempts = int(report.get("repair_attempts", 0))
        controller.usage.context_compactions = int(report.get("context_compactions", 0))
        controller.usage.user_decisions = int(report.get("user_decisions", 0))
        controller.usage.estimated_input_tokens = report.get("estimated_input_tokens")
        controller.usage.estimated_output_tokens = report.get("estimated_output_tokens")
        controller.usage.latest_context_estimated_tokens = int(
            report.get("latest_context_estimated_tokens", 0)
        )
        controller.usage.max_context_estimated_tokens = int(
            report.get("max_context_estimated_tokens", 0)
        )
        controller.usage.latest_observed_prompt_tokens = int(
            report.get("latest_observed_prompt_tokens", 0)
        )
        try:
            controller.usage.context_estimate_calibration = float(
                report.get("context_estimate_calibration", 1.0)
            )
        except (TypeError, ValueError):
            controller.usage.context_estimate_calibration = 1.0
        controller.usage.context_window_tokens = int(report.get("context_window_tokens", 0))
        controller.usage.context_window_ratio = float(report.get("context_window_ratio", 0.0))
        controller.usage.context_pressure_status = str(
            report.get("context_pressure_status", "within_budget")
        )
        latest_sections = report.get("latest_context_sections")
        if isinstance(latest_sections, dict):
            controller.usage.latest_context_sections = {
                str(key): int(value) for key, value in latest_sections.items()
            }
        max_sections = report.get("max_context_sections")
        if isinstance(max_sections, dict):
            controller.usage.max_context_sections = {
                str(key): int(value) for key, value in max_sections.items()
            }
        duplicate_hashes = report.get("context_duplicate_content_hashes")
        if isinstance(duplicate_hashes, list):
            controller.usage.context_duplicate_content_hashes = [
                str(item) for item in duplicate_hashes
            ]
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
        with self._lock:
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
        with self._lock:
            if input_tokens is not None and self.usage.estimated_input_tokens is not None:
                self.usage.estimated_input_tokens += input_tokens
            elif input_tokens is not None:
                self.usage.estimated_input_tokens = None
            if output_tokens is not None and self.usage.estimated_output_tokens is not None:
                self.usage.estimated_output_tokens += output_tokens
            elif output_tokens is not None:
                self.usage.estimated_output_tokens = None

    def record_context_estimate(
        self,
        estimated_tokens: int | None,
        *,
        sections: dict[str, int] | None = None,
        duplicate_content_hashes: list[str] | None = None,
        model_name: str | None = None,
        provider: str | None = None,
    ) -> None:
        if estimated_tokens is None:
            return
        with self._lock:
            raw = max(0, int(estimated_tokens))
            self._last_raw_context_estimate = raw
            # Apply the observed/estimated correction factor learned from real provider usage —
            # the char heuristic systematically drifts per model family; real usage is the truth.
            calibrated = max(0, int(raw * self.usage.context_estimate_calibration))
            pressure = context_pressure(
                self.policy, calibrated, model_name=model_name, provider=provider
            )
            self._apply_context_pressure(pressure)
            if sections:
                clean_sections = {
                    str(key): max(0, _as_int(value)) for key, value in sections.items()
                }
                self.usage.latest_context_sections = clean_sections
                for key, value in clean_sections.items():
                    self.usage.max_context_sections[key] = max(
                        self.usage.max_context_sections.get(key, 0),
                        value,
                    )
            if duplicate_content_hashes:
                merged = [
                    *self.usage.context_duplicate_content_hashes,
                    *[str(item) for item in duplicate_content_hashes],
                ]
                self.usage.context_duplicate_content_hashes = list(dict.fromkeys(merged))[:20]

    def record_context_observation(
        self,
        observed_prompt_tokens: int | None,
        *,
        model_name: str | None = None,
        provider: str | None = None,
    ) -> None:
        """Fold the provider-reported prompt token count back into the pressure signal (S90).

        The char heuristic is a guess; ``response.usage.input_tokens`` is the truth for the very
        request the guess was made for. Two effects: the pressure/ratio of record is overwritten
        with the truth, and the observed/estimated ratio feeds an EMA correction factor applied
        to future pre-call estimates (clamped so one weird report cannot poison the factor)."""
        if not observed_prompt_tokens or observed_prompt_tokens <= 0:
            return
        with self._lock:
            observed = int(observed_prompt_tokens)
            self.usage.latest_observed_prompt_tokens = observed
            raw = getattr(self, "_last_raw_context_estimate", 0)
            if raw > 0:
                ratio = min(4.0, max(0.25, observed / raw))
                self.usage.context_estimate_calibration = round(
                    0.5 * self.usage.context_estimate_calibration + 0.5 * ratio, 4
                )
            pressure = context_pressure(
                self.policy, observed, model_name=model_name, provider=provider
            )
            self._apply_context_pressure(pressure)

    def _apply_context_pressure(self, pressure: ContextPressure) -> None:
        self.usage.latest_context_estimated_tokens = pressure.estimated_tokens
        self.usage.max_context_estimated_tokens = max(
            self.usage.max_context_estimated_tokens,
            pressure.estimated_tokens,
        )
        self.usage.context_window_tokens = pressure.window_tokens
        self.usage.context_window_ratio = pressure.ratio
        self.usage.context_pressure_status = pressure.status
        if pressure.status in {"near_limit", "hard_stop", "exceeded"}:
            warning = (
                "context window is near limit: "
                f"{pressure.estimated_tokens}/{pressure.window_tokens}"
            )
            if warning not in self.usage.warnings:
                self.usage.warnings.append(warning)

    def record_tool_call(self, tool_name: str | None = None) -> None:
        with self._lock:
            tool_class = classify_tool_budget_class(tool_name)
            weight = self._tool_budget_weight(tool_class)
            self.usage.tool_calls += 1
            self.usage.tool_budget_units += weight
            self.usage.tool_call_breakdown[tool_class] = (
                self.usage.tool_call_breakdown.get(tool_class, 0) + 1
            )
            self._check_limit(
                "tool_budget_units",
                self.usage.tool_budget_units,
                "max_tool_calls_per_goal",
            )

    def record_repair_attempt(self) -> None:
        # Intentionally unwired: the effective repair bound is run_command's derived
        # inner-cycle cap plus no-progress detection, which matches the mainstream
        # shape (Codex max-turns; Claude Code consecutive/total block counters). A
        # separate cross-run repair-budget ledger is deliberately not adopted -- the
        # market bounds repair loops with a simple counter, and Codex even deprecated
        # its conditional "on-failure" policy. Kept for callers that opt into an
        # explicit total; wiring it into the default loop would need the DO_NOT_TOUCH
        # execute path. See docs/zh/质量与评估.md §7.
        with self._lock:
            self.usage.repair_attempts += 1
            self._check_limit(
                "repair_attempts",
                self.usage.repair_attempts,
                "max_repair_attempts_total",
            )

    def record_research_call(self) -> None:
        with self._lock:
            self.usage.research_calls += 1
            self._check_limit("research_calls", self.usage.research_calls, "max_research_calls")

    def record_user_decision(self) -> None:
        with self._lock:
            self.usage.user_decisions += 1
            self._check_limit("user_decisions", self.usage.user_decisions, "max_user_decisions")

    def record_context_compaction(self) -> None:
        with self._lock:
            self.usage.context_compactions += 1

    def cost_report(self) -> dict:
        with self._lock:
            status = "within_budget"
            if self.usage.warnings:
                status = "near_limit"
            return {
                "schema_version": "0.1.0",
                "run_id": self.run_id,
                "model_calls": self.usage.model_calls,
                "tool_calls": self.usage.tool_calls,
                "tool_budget_units": self.usage.tool_budget_units,
                "tool_call_breakdown": dict(sorted(self.usage.tool_call_breakdown.items())),
                "estimated_input_tokens": self.usage.estimated_input_tokens,
                "estimated_output_tokens": self.usage.estimated_output_tokens,
                "latest_context_estimated_tokens": self.usage.latest_context_estimated_tokens,
                "max_context_estimated_tokens": self.usage.max_context_estimated_tokens,
                "latest_observed_prompt_tokens": self.usage.latest_observed_prompt_tokens,
                "context_estimate_calibration": round(self.usage.context_estimate_calibration, 4),
                "context_window_tokens": self.usage.context_window_tokens,
                "context_window_ratio": self.usage.context_window_ratio,
                "context_pressure_status": self.usage.context_pressure_status,
                "latest_context_sections": dict(sorted(self.usage.latest_context_sections.items())),
                "max_context_sections": dict(sorted(self.usage.max_context_sections.items())),
                "context_duplicate_content_hashes": list(
                    self.usage.context_duplicate_content_hashes
                ),
                "strong_model_calls": self.usage.strong_model_calls,
                "cheap_model_calls": self.usage.cheap_model_calls,
                "repair_attempts": self.usage.repair_attempts,
                "research_calls": self.usage.research_calls,
                "context_compactions": self.usage.context_compactions,
                "user_decisions": self.usage.user_decisions,
                "status": status,
                "warnings": list(self.usage.warnings),
            }

    @staticmethod
    def pressure(policy: dict, report: dict) -> dict:
        budgets = resolve_budget_limits(policy)
        tool_budget_value = report.get("tool_budget_units", report.get("tool_calls", 0))
        ratios: dict[str, float] = {
            "model_calls": _ratio(
                report.get("model_calls", 0), budgets["max_model_calls_per_goal"]
            ),
            "tool_budget_units": _ratio(tool_budget_value, budgets["max_tool_calls_per_goal"]),
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
        context_ratio = report.get("context_window_ratio")
        if isinstance(context_ratio, (int, float)):
            ratios["context_window"] = max(0.0, float(context_ratio))
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
        limit = int(self.budgets[policy_key])
        if value > limit:
            raise BudgetExceededError(f"{label} exceeded budget: {value} > {limit}")
        if value >= max(1, int(limit * 0.8)):
            warning = f"{label} is near budget: {value}/{limit}"
            if warning not in self.usage.warnings:
                self.usage.warnings.append(warning)

    def _tool_budget_weight(self, tool_class: str) -> int:
        weights = self.policy.get("tool_budget_weights")
        if not isinstance(weights, dict):
            weights = (self.policy.get("budgets") or {}).get("tool_budget_weights")
        if isinstance(weights, dict) and tool_class in weights:
            return max(0, _as_int(weights[tool_class]))
        return DEFAULT_TOOL_BUDGET_WEIGHTS.get(tool_class, DEFAULT_TOOL_BUDGET_WEIGHTS["unknown"])


READ_ONLY_TOOLS = {
    "read_file",
    "list_files",
    "find_files",
    "search_text",
    "diff_workspace",
    "todo_read",
    "recall_memory",
}
VERIFICATION_TOOLS = {"run_tests"}
STATE_TOOLS = {"todo_write", "remember"}
WRITE_TOOLS = {"write_file", "apply_patch", "restore_backup"}
SHELL_TOOLS = {"run_command"}
EXTERNAL_TOOLS = {"mcp", "skill"}

DEFAULT_TOOL_BUDGET_WEIGHTS = {
    "read_only": 0,
    "state": 1,
    "verification": 1,
    "write": 2,
    "shell": 2,
    "external": 3,
    "unknown": 1,
}


def classify_tool_budget_class(tool_name: str | None) -> str:
    normalized = (tool_name or "unknown").strip()
    if normalized in READ_ONLY_TOOLS:
        return "read_only"
    if normalized in VERIFICATION_TOOLS:
        return "verification"
    if normalized in STATE_TOOLS:
        return "state"
    if normalized in WRITE_TOOLS:
        return "write"
    if normalized in SHELL_TOOLS:
        return "shell"
    if normalized in EXTERNAL_TOOLS or normalized.startswith(("mcp.", "skill.")):
        return "external"
    return "unknown"


def resolve_budget_limits(policy: dict) -> dict:
    budgets = dict(policy.get("budgets") or {})
    profile_name = str(policy.get("active_budget_profile") or "").strip()
    profiles = policy.get("budget_profiles")
    if profile_name and isinstance(profiles, dict):
        profile = profiles.get(profile_name)
        if isinstance(profile, dict):
            budgets.update(profile)
            budgets["active_budget_profile"] = profile_name
    return budgets


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
