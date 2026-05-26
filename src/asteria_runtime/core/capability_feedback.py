from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.route_diagnostics import route_diagnostic_for_tier
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class CapabilityFeedbackAdvisor:
    validator: SchemaValidator
    max_hints: int = 5

    def planner_hints(self, agent_dir: Path) -> list[dict]:
        return self._actionable_hints(agent_dir)[: self.max_hints]

    def route_guidance(self, agent_dir: Path) -> dict:
        hints = self._actionable_hints(agent_dir)
        blocking = [item for item in hints if int(item.get("severity") or 0) >= 3]
        review = [item for item in hints if int(item.get("severity") or 0) == 2]
        strategy = self._provider_route_strategy_evaluation(agent_dir)
        status = "healthy"
        if blocking:
            status = "blocked"
        elif review:
            status = "review"
        return {
            "status": status,
            "blocking": blocking,
            "review": review,
            "provider_route_strategy": strategy,
            "recommended_actions": self._route_actions(blocking, review, strategy),
        }

    def goal_spec_execution_plan(self, agent_dir: Path, goal: str) -> dict[str, Any]:
        evaluation = self._provider_route_strategy_evaluation(agent_dir)
        decision = str(evaluation.get("decision") or "unknown")
        low_risk = _is_low_risk_goal_spec_goal(goal)
        plan: dict[str, Any] = {
            "purpose": "goal_spec",
            "default_model_tier": "strong",
            "selected_model_tier": "strong",
            "decision": decision,
            "low_risk_goal": low_risk,
            "reason": str(evaluation.get("reason") or ""),
            "provider_route_strategy": evaluation,
            "actions": [],
        }
        if decision == "retry_or_downgrade":
            plan["actions"].append("retry_strong_goal_spec_once_before_downgrade")
            if low_risk:
                plan["selected_model_tier"] = "medium"
                plan["actions"].append("downgrade_low_risk_goal_spec_to_medium")
        elif decision == "block_gray":
            plan["actions"].append("block_gray_until_strong_goal_spec_stable")
            if low_risk and not _hard_provider_failure(evaluation):
                plan["selected_model_tier"] = "medium"
                plan["actions"].append("downgrade_low_risk_goal_spec_to_medium")
        elif decision == "allow_cost_saver":
            plan["actions"].append("allow_cost_saver_strong_goal_spec_for_small_gray")
        elif decision == "continue_primary":
            plan["actions"].append("continue_primary_strong_goal_spec")
        else:
            plan["actions"].append("collect_goal_spec_route_evidence")
        return plan

    def _actionable_hints(self, agent_dir: Path) -> list[dict]:
        profile_path = agent_dir / "model" / "capability_profile.json"
        if not profile_path.exists():
            return []
        profile = JsonStore(self.validator).read(profile_path, "model_capability_profile")
        profiles = [item for item in profile.get("profiles", []) if isinstance(item, dict)]
        hints = [self._hint(item) for item in profiles]
        matrix_hints = [self._matrix_hint(item) for item in profiles]
        hints.extend(matrix_hints)
        strategy_hint = self._provider_route_strategy_hint(agent_dir, profiles)
        if strategy_hint:
            hints.append(strategy_hint)
        actionable = [hint for hint in hints if hint]
        actionable.sort(key=lambda item: (item["severity"], item["purpose"]), reverse=True)
        return actionable

    def _hint(self, profile: dict) -> dict:
        action = str(profile.get("recommended_action") or "")
        purpose = str(profile.get("purpose") or "unknown")
        provider = str(profile.get("provider") or "unknown")
        model = str(profile.get("model") or "unknown")
        tier = str(profile.get("model_tier") or "unknown")
        if action in {"", "keep_route", "collect_more_data"}:
            return {}
        severity = 2
        if action in {"pause_route_until_config_fixed", "review_worker_route_before_scaling"}:
            severity = 3
        if action == "improve_planner_scope_before_scaling":
            message = "prefer narrower read/write scope before scaling similar tasks"
        elif action == "review_merge_quality_before_scaling":
            message = "tighten write_scope and verification before promoting similar tasks"
        elif action == "review_validation_or_route_before_scaling":
            message = "prefer stronger verification or a different route for similar tasks"
        else:
            message = action.replace("_", " ")
        return {
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "model_tier": tier,
            "recommended_action": action,
            "message": message,
            "severity": severity,
        }


    def _matrix_hint(self, profile: dict) -> dict:
        total = int(profile.get("matrix_signal_total") or 0)
        if total <= 0:
            return {}
        success_rate = float(profile.get("matrix_signal_success_rate") or 0.0)
        if success_rate >= 0.8:
            return {}
        provider = str(profile.get("provider") or "unknown")
        model = str(profile.get("model") or "unknown")
        purpose = str(profile.get("purpose") or "unknown")
        tier = str(profile.get("model_tier") or "unknown")
        raw_routes = profile.get("matrix_routes")
        routes: dict[str, Any] = raw_routes if isinstance(raw_routes, dict) else {}
        raw_task_kinds = profile.get("matrix_task_kinds")
        task_kinds: dict[str, Any] = raw_task_kinds if isinstance(raw_task_kinds, dict) else {}
        dominant_route = _top_counter_key(routes)
        dominant_task_kind = _top_counter_key(task_kinds)
        message = (
            f"real-provider matrix is weak for {dominant_task_kind}/{dominant_route}; "
            "review route before widening gray or long-run budget"
        )
        severity = 3 if total >= 3 and success_rate < 0.5 else 2
        return {
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "model_tier": tier,
            "recommended_action": "review_real_provider_matrix_before_scaling",
            "message": message,
            "severity": severity,
            "matrix_signal_total": total,
            "matrix_signal_success_rate": success_rate,
            "matrix_routes": routes,
            "matrix_task_kinds": task_kinds,
        }

    def _route_actions(
        self,
        blocking: list[dict],
        review: list[dict],
        strategy: dict[str, Any] | None = None,
    ) -> list[str]:
        strategy = strategy or {}
        matrix_blocking = any(
            item.get("recommended_action") == "review_real_provider_matrix_before_scaling"
            for item in blocking
        )
        matrix_review = any(
            item.get("recommended_action") == "review_real_provider_matrix_before_scaling"
            for item in review
        )
        if blocking:
            actions = [
                "Pause scaling affected routes until provider, worker, or budget issues are resolved.",
                "Run `asteria capability-report` after collecting fresh evidence.",
            ]
            if matrix_blocking:
                actions.insert(
                    0,
                    "Do not widen real-provider matrix routes until failed task_kind/route evidence is repaired or rerun.",
                )
            if strategy.get("decision") == "block_gray":
                actions.insert(
                    0,
                    "Do not widen small real-task gray until strong goal_spec route meets provider strategy thresholds.",
                )
            return actions
        if review:
            actions = [
                "Review affected route purposes before increasing long-run budget.",
                "Prefer smaller scoped tasks or stronger verification for matching work.",
            ]
            if matrix_review:
                actions.insert(
                    0,
                    "Review real-provider matrix task_kind/route failures before increasing gray batch size.",
                )
            if strategy.get("decision") == "retry_or_downgrade":
                actions.append(
                    "Use the configured retry/downgrade path for strong goal_spec before increasing batch size."
                )
            return actions
        return ["Keep current model routes and continue collecting capability evidence."]

    def _provider_route_strategy_hint(
        self,
        agent_dir: Path,
        profiles: list[dict[str, Any]],
    ) -> dict:
        evaluation = self._provider_route_strategy_evaluation(agent_dir, profiles)
        decision = str(evaluation.get("decision") or "")
        if decision == "block_gray":
            return {
                "purpose": "goal_spec",
                "provider": str(evaluation.get("provider") or "unknown"),
                "model": str(evaluation.get("model") or "unknown"),
                "model_tier": "strong",
                "recommended_action": "block_gray_until_strong_goal_spec_stable",
                "message": str(evaluation.get("reason") or "strong goal_spec route is unstable"),
                "severity": 3,
            }
        if decision == "retry_or_downgrade":
            return {
                "purpose": "goal_spec",
                "provider": str(evaluation.get("provider") or "unknown"),
                "model": str(evaluation.get("model") or "unknown"),
                "model_tier": "strong",
                "recommended_action": "retry_or_downgrade_strong_goal_spec",
                "message": str(evaluation.get("reason") or "strong goal_spec route needs review"),
                "severity": 2,
            }
        return {}

    def _provider_route_strategy_evaluation(
        self,
        agent_dir: Path,
        profiles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        strategy = self._strong_goal_spec_strategy(agent_dir)
        if not strategy:
            return {"decision": "not_configured"}
        if profiles is None:
            profile_path = agent_dir / "model" / "capability_profile.json"
            if not profile_path.exists():
                return {
                    "decision": "collect_evidence",
                    "strategy": strategy,
                    "reason": "No model capability profile exists yet.",
                }
            profile = JsonStore(self.validator).read(profile_path, "model_capability_profile")
            profiles = [item for item in profile.get("profiles", []) if isinstance(item, dict)]

        candidates = [
            item
            for item in profiles
            if str(item.get("purpose") or "") == "goal_spec"
            and str(item.get("model_tier") or "") == "strong"
        ]
        current_model = _current_configured_strong_model()
        if current_model:
            current_candidates = [
                item for item in candidates if str(item.get("model") or "") == current_model
            ]
            if current_candidates:
                candidates = current_candidates
            elif candidates:
                return {
                    "decision": "collect_evidence",
                    "strategy": strategy,
                    "current_model": current_model,
                    "reason": (
                        "No strong goal_spec route evidence exists for the current configured "
                        "strong model."
                    ),
                }
        if not candidates:
            return {
                "decision": "collect_evidence",
                "strategy": strategy,
                "reason": "No strong goal_spec route evidence exists yet.",
            }

        selected = max(candidates, key=lambda item: int(item.get("total_calls") or 0))
        total = int(selected.get("total_calls") or 0)
        success_rate = float(selected.get("success_rate") or 0.0)
        raw_failure_types = selected.get("failure_types")
        failure_types: dict[str, Any] = (
            raw_failure_types if isinstance(raw_failure_types, dict) else {}
        )
        timeout_failures = int(failure_types.get("timeout") or 0)
        min_calls = int(strategy.get("min_calls_before_enforcement") or 3)
        min_success = float(strategy.get("min_success_rate_for_gray") or 0.8)
        max_timeouts = int(strategy.get("max_timeout_failures_for_gray") or 1)
        provider = str(selected.get("provider") or "unknown")
        model = str(selected.get("model") or "unknown")

        base = {
            "strategy": strategy,
            "provider": provider,
            "model": model,
            "total_calls": total,
            "success_rate": success_rate,
            "timeout_failures": timeout_failures,
            "min_calls_before_enforcement": min_calls,
            "min_success_rate_for_gray": min_success,
            "max_timeout_failures_for_gray": max_timeouts,
        }
        if failure_types.get("authentication") or failure_types.get("budget"):
            return {
                **base,
                "decision": "block_gray",
                "reason": "Strong goal_spec route has authentication or budget failures.",
            }
        if timeout_failures > max_timeouts:
            return {
                **base,
                "decision": "block_gray",
                "reason": "Strong goal_spec timeout failures exceed provider route strategy threshold.",
            }
        if total >= min_calls and success_rate < min_success:
            return {
                **base,
                "decision": "block_gray",
                "reason": "Strong goal_spec success rate is below provider route strategy threshold.",
            }
        if (
            failure_types.get("timeout")
            or failure_types.get("rate_limited")
            or failure_types.get("network")
        ):
            return {
                **base,
                "decision": "retry_or_downgrade",
                "reason": "Strong goal_spec route has transient provider failures; use configured retry/downgrade path before widening scope.",
            }
        if model == str(strategy.get("cost_saver_model") or "") and total >= min_calls:
            return {
                **base,
                "decision": "allow_cost_saver",
                "reason": "Cost-saver strong model has enough healthy evidence for small gray tasks.",
            }
        return {
            **base,
            "decision": "continue_primary",
            "reason": "Strong goal_spec route is within configured provider strategy thresholds.",
        }

    def _strong_goal_spec_strategy(self, agent_dir: Path) -> dict[str, Any]:
        try:
            policy = load_policy_config(agent_dir, self.validator)
        except (OSError, ValueError):
            policy = {}
        route_strategy = policy.get("provider_route_strategy")
        route_strategy = route_strategy if isinstance(route_strategy, dict) else {}
        strategy = route_strategy.get("strong_goal_spec")
        return strategy if isinstance(strategy, dict) else {}


def _top_counter_key(counter: dict[str, Any]) -> str:
    if not counter:
        return "unknown"
    return max(counter.items(), key=lambda item: int(item[1] or 0))[0]


def _hard_provider_failure(evaluation: dict[str, Any]) -> bool:
    reason = str(evaluation.get("reason") or "").lower()
    return "authentication" in reason or "budget" in reason


def _current_configured_strong_model() -> str:
    diagnostic = route_diagnostic_for_tier("strong")
    if not diagnostic.configured or not diagnostic.model_name:
        return ""
    return diagnostic.model_name


def _is_low_risk_goal_spec_goal(goal: str) -> bool:
    text = goal.lower()
    doc_signals = (
        "doc",
        "docs",
        "documentation",
        "readme",
        "markdown",
        "runbook",
        "说明",
        "文档",
        "手册",
    )
    code_signals = (
        "src/",
        "test",
        "pytest",
        "implement",
        "refactor",
        "fix",
        "cli",
        "api",
        "代码",
        "实现",
        "修复",
        "重构",
    )
    return any(signal in text for signal in doc_signals) and not any(
        signal in text for signal in code_signals
    )
