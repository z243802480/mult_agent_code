from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.route_diagnostics import route_diagnostic_for_tier
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
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
        elif decision == "block_validation":
            plan["actions"].append("block_validation_until_strong_goal_spec_stable")
            if low_risk and not _hard_provider_failure(evaluation):
                plan["selected_model_tier"] = "medium"
                plan["actions"].append("downgrade_low_risk_goal_spec_to_medium")
        elif decision == "allow_cost_saver":
            plan["actions"].append("allow_cost_saver_strong_goal_spec_for_small_validation")
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
            "review route before widening validation or long-run budget"
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
            if strategy.get("decision") == "block_validation":
                actions.insert(
                    0,
                    "Do not widen small real-task validation until strong goal_spec route meets provider strategy thresholds.",
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
                    "Review real-provider matrix task_kind/route failures before increasing validation batch size.",
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
        if decision == "block_validation":
            return {
                "purpose": "goal_spec",
                "provider": str(evaluation.get("provider") or "unknown"),
                "model": str(evaluation.get("model") or "unknown"),
                "model_tier": "strong",
                "recommended_action": "block_validation_until_strong_goal_spec_stable",
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
                item
                for item in candidates
                if _model_names_match(str(item.get("model") or ""), current_model)
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
        min_success = float(strategy.get("min_success_rate_for_validation") or 0.8)
        max_timeouts = int(strategy.get("max_timeout_failures_for_validation") or 1)
        provider = str(selected.get("provider") or "unknown")
        model = str(selected.get("model") or "unknown")
        fresh_window = self._fresh_strong_goal_spec_window(
            agent_dir=agent_dir,
            provider=provider,
            model=model,
            min_calls=min_calls,
            min_success=min_success,
            max_timeouts=max_timeouts,
        )

        base = {
            "strategy": strategy,
            "provider": provider,
            "model": model,
            "current_model": current_model,
            "total_calls": total,
            "success_rate": success_rate,
            "timeout_failures": timeout_failures,
            "min_calls_before_enforcement": min_calls,
            "min_success_rate_for_validation": min_success,
            "max_timeout_failures_for_validation": max_timeouts,
            "fresh_evidence_window": fresh_window,
        }
        if failure_types.get("authentication") or failure_types.get("budget"):
            return {
                **base,
                "decision": "block_validation",
                "reason": "Strong goal_spec route has authentication or budget failures.",
            }
        if timeout_failures > max_timeouts:
            if fresh_window.get("status") == "healthy":
                return {
                    **base,
                    "decision": "retry_or_downgrade",
                    "reason": "Historical strong goal_spec timeouts exceed threshold, but recent evidence is clean; keep retry/downgrade guard before widening scope.",
                }
            return {
                **base,
                "decision": "block_validation",
                "reason": self._fresh_window_reason(
                    fresh_window,
                    "Strong goal_spec timeout failures exceed provider route strategy threshold.",
                ),
            }
        if total >= min_calls and success_rate < min_success:
            if fresh_window.get("status") == "healthy":
                return {
                    **base,
                    "decision": "retry_or_downgrade",
                    "reason": "Historical strong goal_spec success rate is below threshold, but recent evidence is clean; keep retry/downgrade guard before widening scope.",
                }
            return {
                **base,
                "decision": "block_validation",
                "reason": self._fresh_window_reason(
                    fresh_window,
                    "Strong goal_spec success rate is below provider route strategy threshold.",
                ),
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
                "reason": "Cost-saver strong model has enough healthy evidence for small validation tasks.",
            }
        return {
            **base,
            "decision": "continue_primary",
            "reason": "Strong goal_spec route is within configured provider strategy thresholds.",
        }

    def _fresh_window_reason(self, window: dict[str, Any], fallback: str) -> str:
        if not window:
            return fallback
        status = str(window.get("status") or "")
        if status == "needs_more_evidence":
            remaining = int(window.get("remaining_successes_needed") or 0)
            return (
                f"{fallback} Recent window needs {remaining} more successful "
                "strong goal_spec call(s) before recovery."
            )
        if status == "blocked":
            return f"{fallback} Recent window still contains provider failures."
        return fallback

    def _fresh_strong_goal_spec_window(
        self,
        *,
        agent_dir: Path,
        provider: str,
        model: str,
        min_calls: int,
        min_success: float,
        max_timeouts: int,
    ) -> dict[str, Any]:
        calls: list[dict[str, Any]] = []
        store = JsonlStore(self.validator)
        runs_dir = agent_dir / "runs"
        if runs_dir.exists():
            for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
                path = run_dir / "model_calls.jsonl"
                if not path.exists():
                    continue
                calls.extend(store.read_all(path, "model_call"))
        matching = [
            call
            for call in calls
            if str(call.get("purpose") or "") == "goal_spec"
            and str(call.get("model_tier") or "") == "strong"
            and str(call.get("model_provider") or "") == provider
            and _model_names_match(str(call.get("model_name") or ""), model)
        ]
        route_checks = self._fresh_model_route_checks(
            agent_dir=agent_dir,
            provider=provider,
            model=model,
        )
        matching.extend(route_checks)
        matching.sort(key=lambda call: str(call.get("created_at") or ""))
        window_size = max(min_calls, 5)
        window = matching[-window_size:]
        summary = _summarize_fresh_model_call_window(
            window,
            min_calls=min_calls,
            min_success=min_success,
            max_timeouts=max_timeouts,
        )
        if not matching and not runs_dir.exists():
            return {
                **summary,
                "status": "missing",
            }
        return summary

    def _fresh_model_route_checks(
        self,
        *,
        agent_dir: Path,
        provider: str,
        model: str,
    ) -> list[dict[str, Any]]:
        path = agent_dir / "model" / "model_route_checks.jsonl"
        if not path.exists():
            return []
        checks = JsonlStore(self.validator).read_all(path, "model_route_check")
        return [
            {
                "created_at": check.get("created_at"),
                "status": check.get("status"),
                "summary": check.get("summary"),
                "streaming": check.get("streaming"),
                "duration_ms": check.get("duration_ms"),
                "deadline_ms": check.get("deadline_ms"),
                "model_provider": check.get("provider"),
                "model_name": check.get("model_name"),
                "model_tier": check.get("tier"),
                "purpose": "model_check",
            }
            for check in checks
            if str(check.get("tier") or "") == "strong"
            and str(check.get("provider") or "") == provider
            and _model_names_match(str(check.get("model_name") or ""), model)
        ]

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


def _model_names_match(left: str, right: str) -> bool:
    left = left.strip()
    right = right.strip()
    if left == right:
        return True
    glm5_aliases = {"glm-5", "glm-5.1"}
    return left in glm5_aliases and right in glm5_aliases


def _summarize_fresh_model_call_window(
    calls: list[dict[str, Any]],
    *,
    min_calls: int,
    min_success: float,
    max_timeouts: int,
) -> dict[str, Any]:
    success_calls = sum(1 for call in calls if str(call.get("status") or "") == "success")
    failure_calls = len(calls) - success_calls
    failure_types: dict[str, int] = {}
    for call in calls:
        if str(call.get("status") or "") == "success":
            continue
        failure_type = _model_call_failure_type(call)
        failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
    total = len(calls)
    success_rate = round(success_calls / total, 4) if total else 0.0
    timeout_failures = int(failure_types.get("timeout") or 0)
    status = "healthy"
    if total < min_calls:
        status = "needs_more_evidence"
    elif success_rate < min_success or timeout_failures > max_timeouts:
        status = "blocked"
    remaining_successes = max(0, min_calls - success_calls)
    latest = calls[-1] if calls else {}
    latest_failure = next(
        (call for call in reversed(calls) if str(call.get("status") or "") != "success"),
        {},
    )
    latest_success = next(
        (call for call in reversed(calls) if str(call.get("status") or "") == "success"),
        {},
    )
    return {
        "status": status,
        "window_size": max(min_calls, 5),
        "total_calls": total,
        "success_calls": success_calls,
        "failure_calls": failure_calls,
        "success_rate": success_rate,
        "failure_types": failure_types,
        "timeout_failures": timeout_failures,
        "required_successes": min_calls,
        "remaining_successes_needed": remaining_successes,
        "latest_call_at": str(latest.get("created_at") or ""),
        "latest_success_at": str(latest_success.get("created_at") or ""),
        "latest_failure_at": str(latest_failure.get("created_at") or ""),
    }


def _model_call_failure_type(call: dict[str, Any]) -> str:
    summary = str(call.get("summary") or "").lower()
    streaming = call.get("streaming")
    streaming = streaming if isinstance(streaming, dict) else {}
    error_type = str(streaming.get("error_type") or "").lower()
    duration_ms = int(call.get("duration_ms") or 0)
    deadline_ms = int(call.get("deadline_ms") or 0)
    if "auth" in summary or "api key" in summary or "unauthorized" in summary:
        return "authentication"
    if "budget" in summary or "quota" in summary:
        return "budget"
    if "rate limit" in summary or "rate_limited" in error_type:
        return "rate_limited"
    if "timed out" in summary or "timeout" in summary:
        return "timeout"
    if deadline_ms > 0 and duration_ms >= deadline_ms:
        return "timeout"
    if "ssl" in summary or "urlopen" in summary or "network" in summary or "eof" in summary:
        return "network"
    if error_type:
        return error_type
    return "model_call_failed"


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
