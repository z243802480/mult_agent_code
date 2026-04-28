from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator
from agent_runtime.utils.time import now_iso


class BrainstormAgentError(RuntimeError):
    pass


@dataclass
class BrainstormAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def generate(
        self,
        goal: str,
        project_context: dict,
        run_id: str | None,
        max_candidates: int = 5,
    ) -> dict:
        request = ChatRequest(
            purpose="brainstorming",
            model_tier="strong",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(
                    role="user",
                    content=self._user_prompt(goal, project_context, run_id, max_candidates),
                ),
            ],
            response_format="json",
            temperature=0.35,
            max_output_tokens=5000,
            metadata={"run_id": run_id, "agent_id": "BrainstormAgent"},
        )
        response = self.model_client.chat(request)
        report = self._parse_json(response.content)
        report.setdefault("schema_version", "0.1.0")
        report.setdefault("run_id", run_id)
        report.setdefault("goal", goal)
        report.setdefault("created_at", now_iso())
        try:
            self.validator.validate("brainstorm_report", report)
        except SchemaValidationError as exc:
            raise BrainstormAgentError(f"BrainstormReport failed schema validation: {exc}") from exc
        return report

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BrainstormAgentError(f"Brainstorm response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BrainstormAgentError("Brainstorm response must be a JSON object")
        return parsed

    def _system_prompt(self) -> str:
        return """You are BrainstormAgent for a local-first autonomous development runtime.

Return only valid JSON matching the BrainstormReport schema. Do not wrap in markdown.

Rules:
- Generate divergent candidates, then converge on one recommendation.
- Score candidates from 0.0 to 1.0 for goal fit, feasibility, cost, value, risk, novelty, and verification difficulty.
- Convert the recommendation into concrete task_candidates and decision_candidates.
- Do not implement code. Brainstorming creates planning artifacts only.
- Prefer local-first, privacy-safe, testable, modest-scope directions.
"""

    def _user_prompt(
        self,
        goal: str,
        project_context: dict,
        run_id: str | None,
        max_candidates: int,
    ) -> str:
        payload = {
            "run_id": run_id,
            "goal": goal,
            "max_candidates": max_candidates,
            "project_context": project_context,
            "required_output_shape": {
                "schema_version": "0.1.0",
                "run_id": run_id,
                "goal": goal,
                "created_at": "ISO-8601 timestamp",
                "candidates": [
                    {
                        "candidate_id": "candidate-0001",
                        "title": "candidate title",
                        "description": "candidate description",
                        "scores": {
                            "goal_fit": 0.9,
                            "feasibility": 0.8,
                            "cost": 0.4,
                            "user_value": 0.8,
                            "risk": 0.3,
                            "novelty": 0.5,
                            "verification_difficulty": 0.4,
                        },
                        "risks": ["risk"],
                    }
                ],
                "recommendation": {
                    "candidate_id": "candidate-0001",
                    "reason": "why this should be selected",
                },
                "task_candidates": [
                    {
                        "title": "task title",
                        "description": "task description",
                        "priority": "high",
                        "role": "CoderAgent",
                        "acceptance": ["observable acceptance"],
                        "expected_artifacts": ["relative/path"],
                    }
                ],
                "decision_candidates": [
                    {
                        "question": "decision question",
                        "recommended_option_id": "option-1",
                        "default_option_id": "option-1",
                        "options": [
                            {
                                "option_id": "option-1",
                                "label": "option",
                                "tradeoff": "tradeoff",
                                "action": "create_task",
                            },
                            {
                                "option_id": "defer",
                                "label": "defer",
                                "tradeoff": "tradeoff",
                                "action": "record_constraint",
                            },
                        ],
                        "impact": {
                            "scope": "medium",
                            "budget": "medium",
                            "risk": "medium",
                            "quality": "medium",
                        },
                    }
                ],
                "summary": "short summary",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
