from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class ReviewAgentError(RuntimeError):
    pass


@dataclass
class ReviewAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def evaluate(self, review_context: dict, run_id: str) -> dict:
        request = ChatRequest(
            purpose="run_review",
            model_tier="strong",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=json.dumps(review_context, ensure_ascii=False, indent=2)),
            ],
            response_format="json",
            temperature=0.1,
            max_output_tokens=5000,
            metadata={"run_id": run_id, "agent_id": "ReviewAgent"},
        )
        response = self.model_client.chat(request)
        report = self._parse_json(response.content)
        report = self._normalize(report, review_context, run_id)
        try:
            self.validator.validate("eval_report", report)
        except SchemaValidationError as exc:
            raise ReviewAgentError(f"EvalReport failed schema validation: {exc}") from exc
        return report

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
        normalized["overall"] = self._overall(normalized.get("overall"), deterministic_status)
        return normalized

    def _object(self, value: object, default: dict) -> dict:
        if isinstance(value, dict):
            merged = dict(default)
            merged.update(value)
            return merged
        return default

    def _overall(self, value: object, default_status: str) -> dict:
        if isinstance(value, dict):
            status = str(value.get("status") or default_status).lower()
            if status not in {"pass", "partial", "fail"}:
                status = default_status
            score = value.get("score", 0.9 if status == "pass" else 0.6 if status == "partial" else 0.2)
            reason = str(value.get("reason") or f"Deterministic checks indicate {status}.")
            return {"status": status, "score": float(score), "reason": reason}
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
- Mark status as pass only when the run is usable, verified, and within budget.
- Mark partial when the result is useful but has clear gaps.
- Mark fail when the result is unusable, unverified, unsafe, or materially off-goal.
"""
