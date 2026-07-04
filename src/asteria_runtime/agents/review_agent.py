from __future__ import annotations

import json
import time
from dataclasses import dataclass

from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class ReviewAgentError(RuntimeError):
    pass


@dataclass
class ReviewAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def evaluate(self, review_context: dict, run_id: str) -> dict:
        parse_error: ReviewAgentError | None = None
        model_call_errors: list[dict[str, str]] = []
        role_contract = role_contract_for(
            role="ReviewAgent",
            purpose="run_review",
            policy=review_context.get("policy") if isinstance(review_context.get("policy"), dict) else None,
        )
        response_content: str | None = None
        selected_tier = "strong"
        review_started = time.monotonic()
        total_budget = self._fallback_total_budget_seconds(review_context)
        for index, tier in enumerate(self._fallback_tiers(review_context)):
            # Each tier is an independent full-deadline provider call; without a total
            # budget a 3-tier timeout chain (strong->medium->cheap) can dominate the task
            # budget. Once the cumulative budget is spent, stop and fall back to
            # deterministic checks instead of chasing more timeouts.
            if (
                index > 0
                and total_budget is not None
                and time.monotonic() - review_started >= total_budget
            ):
                model_call_errors.append(
                    {
                        "model_tier": tier,
                        "error_type": "ReviewFallbackBudgetExceeded",
                        "summary": (
                            f"review fallback total budget {total_budget:.0f}s exceeded; "
                            "skipped remaining tiers"
                        ),
                    }
                )
                break
            selected_tier = tier
            request = self._request(review_context, run_id, tier, role_contract.to_dict())
            try:
                response = self.model_client.chat(request)
            except Exception as exc:  # noqa: BLE001 - provider boundary fallback is audited below
                model_call_errors.append(
                    {
                        "model_tier": tier,
                        "error_type": type(exc).__name__,
                        "summary": str(exc),
                    }
                )
                continue
            response_content = response.content
            break
        if response_content is None:
            report = {}
        else:
            try:
                report = self._parse_json(response_content)
            except ReviewAgentError as exc:
                parse_error = exc
                report = {}
        report = self._normalize(report, review_context, run_id)
        if parse_error:
            report["overall"]["reason"] = (
                f"{report['overall']['reason']} Model review returned non-JSON; "
                "deterministic runtime checks were used for the structured report."
            )
            report["trajectory_eval"]["review_model_parse_error"] = str(parse_error)
        if model_call_errors:
            report["trajectory_eval"]["review_model_call_errors"] = model_call_errors
            report["trajectory_eval"]["review_fallback"] = {
                "used": response_content is None,
                "source": "deterministic_checks" if response_content is None else "model_tier_retry",
                "attempted_tiers": [item["model_tier"] for item in model_call_errors],
                "selected_tier": None if response_content is None else selected_tier,
                "reason": model_call_errors[0]["summary"],
            }
            if response_content is None:
                report["overall"]["reason"] = (
                    f"{report['overall']['reason']} Review model calls failed; "
                    "deterministic runtime checks were used as an auditable fallback."
                )
        try:
            self.validator.validate("eval_report", report)
        except SchemaValidationError as exc:
            raise ReviewAgentError(f"EvalReport failed schema validation: {exc}") from exc
        return report

    def _request(
        self,
        review_context: dict,
        run_id: str,
        model_tier: str,
        role_contract: dict,
    ) -> ChatRequest:
        request = ChatRequest(
            purpose="run_review",
            model_tier=model_tier,
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=json.dumps(review_context, ensure_ascii=False, indent=2)),
            ],
            response_format="json",
            temperature=0.1,
            max_output_tokens=5000,
            metadata={
                "run_id": run_id,
                "agent_id": "ReviewAgent",
                "agent_role_contract": role_contract,
                **self._prompt_envelope_metadata(review_context),
            },
        )
        return request

    def _fallback_tiers(self, review_context: dict) -> list[str]:
        configured = review_context.get("review_model_fallback_tiers")
        if isinstance(configured, list):
            tiers = [str(item).strip().lower() for item in configured]
        else:
            tiers = ["strong", "medium", "cheap"]
        return [tier for tier in dict.fromkeys(tiers) if tier in {"strong", "medium", "cheap"}]

    def _fallback_total_budget_seconds(self, review_context: dict) -> float | None:
        # Wall-clock cap across all review fallback tiers. `<= 0` disables the cap;
        # default keeps review from dominating the task budget under provider timeouts.
        value = review_context.get("review_fallback_total_seconds")
        if isinstance(value, bool):
            return 120.0
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        return 120.0

    def _prompt_envelope_metadata(self, review_context: dict) -> dict:
        metadata: dict = {}
        envelope = review_context.get("prompt_envelope")
        if isinstance(envelope, dict):
            metadata.update(
                {
                    "prompt_envelope_hash": envelope.get("content_hash"),
                    "prompt_envelope_path": envelope.get("path"),
                    "capability_manifest_hash": envelope.get("capability_manifest_hash"),
                }
            )
        context_policy = review_context.get("context_policy")
        if isinstance(context_policy, dict):
            metadata["context_mode"] = context_policy.get("mode")
            fast_path = context_policy.get("fast_path")
            if isinstance(fast_path, dict):
                metadata["fast_path_task_kind"] = fast_path.get("task_kind")
        return metadata

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise ReviewAgentError(f"Review response was not valid JSON: {exc}") from exc
        return parsed

    def _normalize(self, report: dict, review_context: dict, run_id: str) -> dict:
        normalized = dict(report)
        checks = review_context.get("deterministic_checks", {})
        cost_report = review_context.get("cost_report", {})
        completion = float(checks.get("task_completion_rate", 0))
        blocked = int(checks.get("blocked_task_count", 0))
        verification = float(checks.get("verification_pass_rate", 0))
        deterministic_status = (
            "pass"
            if completion >= 1.0 and blocked == 0
            else "partial"
            if completion > 0 and blocked <= 1
            else "fail"
        )
        normalized["schema_version"] = str(normalized.get("schema_version") or "0.1.0")
        normalized["run_id"] = normalized.get("run_id", run_id)
        normalized["goal_eval"] = self._object(
            normalized.get("goal_eval"),
            {"requirement_coverage": completion},
        )
        normalized["artifact_eval"] = self._object(
            normalized.get("artifact_eval"),
            {"artifacts_present": completion > 0, "logs_present": True},
        )
        normalized["outcome_eval"] = self._object(
            normalized.get("outcome_eval"),
            {"verification_pass_rate": verification, "run_success": deterministic_status == "pass"},
        )
        normalized["trajectory_eval"] = self._object(
            normalized.get("trajectory_eval"),
            {"blocked_task_count": blocked},
        )
        normalized["cost_eval"] = self._object(
            normalized.get("cost_eval"),
            {
                "status": cost_report.get("status", "within_budget"),
                "model_calls": cost_report.get("model_calls", 0),
                "tool_calls": cost_report.get("tool_calls", 0),
            },
        )
        correctness = review_context.get("correctness_signal")
        normalized["overall"] = self._overall(
            normalized.get("overall"),
            deterministic_status,
            correctness if isinstance(correctness, dict) else None,
        )
        return normalized

    def _object(self, value: object, default: dict) -> dict:
        if isinstance(value, dict):
            merged = dict(default)
            merged.update(value)
            return merged
        return default

    def _overall(
        self, value: object, default_status: str, correctness: dict | None = None
    ) -> dict:
        # Honest score: when the run has real executable-verification evidence, prefer that
        # graded pass rate over the 0.9/0.6/0.2 status-bucketed constant. ``correctness`` is
        # None when no run_tests/run_command ran (docs/creative tasks) — there we keep the
        # deterministic constant rather than fabricate a fail against a non-verification task.
        real_score = float(correctness["score"]) if isinstance(correctness, dict) else None
        if isinstance(value, dict):
            status = str(value.get("status") or default_status).lower()
            if status not in {"pass", "partial", "fail"}:
                status = default_status
            constant = 0.9 if status == "pass" else 0.6 if status == "partial" else 0.2
            model_score = value.get("score")
            # Respect an explicit model score (a real judgment); only the constant fallback is
            # replaced with the real verification pass rate.
            score = model_score if model_score is not None else (real_score if real_score is not None else constant)
            reason = str(value.get("reason") or f"Deterministic checks indicate {status}.")
            if model_score is None and real_score is not None:
                reason = f"{reason} Score is the real verification pass rate ({real_score:.2f})."
            return {"status": status, "score": float(score), "reason": reason}
        if real_score is not None:
            # Pure-deterministic review (model absent/failed) with real verification evidence:
            # the graded correctness verdict is authoritative for status, score, and reason.
            return {
                "status": str(correctness["status"]),
                "score": real_score,
                "reason": str(correctness["reason"]),
            }
        return {
            "status": default_status,
            "score": 0.9 if default_status == "pass" else 0.6 if default_status == "partial" else 0.2,
            "reason": f"Deterministic checks indicate {default_status}.",
        }

    def _system_prompt(self) -> str:
        return """You are ReviewAgent for an autonomous development runtime.

Return only valid JSON matching the EvalReport schema. Do not wrap in markdown.

You must:
- Evaluate goal understanding, artifacts, outcome, trajectory, and cost.
- Use the supplied logs and task board as evidence.
- Penalize missing verification, blocked tasks, missing artifacts, unsafe actions, or uncontrolled cost.
- When tool_observation_actions are present, use them as explicit review choices:
  diagnose unresolved failures, repair scoped defects, replan wrong task contracts,
  ask for decisions when policy/scope/budget blocks progress, or stop unsafe work.
- Mark status as pass only when the run is usable, verified, and within budget.
- Mark partial when the result is useful but has clear gaps.
- Mark fail when the result is unusable, unverified, unsafe, or materially off-goal.
"""
