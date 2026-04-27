from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
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
        try:
            self.validator.validate("eval_report", report)
        except SchemaValidationError as exc:
            raise ReviewAgentError(f"EvalReport failed schema validation: {exc}") from exc
        return report

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ReviewAgentError(f"Review response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ReviewAgentError("Review response must be a JSON object")
        return parsed

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
