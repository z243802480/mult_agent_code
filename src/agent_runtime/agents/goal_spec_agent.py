from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class GoalSpecError(RuntimeError):
    pass


@dataclass
class GoalSpecAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def generate(self, goal: str, project_context: dict, run_id: str) -> dict:
        request = ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=self._user_prompt(goal, project_context)),
            ],
            response_format="json",
            temperature=0.2,
            max_output_tokens=4000,
            metadata={"run_id": run_id, "agent_id": "GoalSpecAgent"},
        )
        response = self.model_client.chat(request)
        data = self._parse_json(response.content)
        try:
            self.validator.validate("goal_spec", data)
        except SchemaValidationError as exc:
            raise GoalSpecError(f"GoalSpec failed schema validation: {exc}") from exc
        return data

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise GoalSpecError(f"GoalSpec response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise GoalSpecError("GoalSpec response must be a JSON object")
        return parsed

    def _system_prompt(self) -> str:
        return """You are GoalSpecAgent for a local-first autonomous development runtime.

Return only valid JSON matching the GoalSpec schema. Do not wrap in markdown.

You must:
- Preserve the original user goal.
- Normalize it into a coherent product or engineering goal.
- Infer reasonable missing requirements without excessive scope expansion.
- Separate assumptions, constraints, non-goals, and expanded requirements.
- Include must/should/could priorities.
- Include a verifiable definition_of_done and verification_strategy.
- Prefer local-first and privacy-safe defaults.
"""

    def _user_prompt(self, goal: str, project_context: dict) -> str:
        return f"""User goal:
{goal}

Project context:
{json.dumps(project_context, ensure_ascii=False, indent=2)}

Return this exact JSON shape:
{{
  "schema_version": "0.1.0",
  "goal_id": "goal-0001",
  "original_goal": "...",
  "normalized_goal": "...",
  "goal_type": "software_tool|codebase_improvement|research|report|knowledge_base|automation|unknown",
  "assumptions": [],
  "constraints": [],
  "non_goals": [],
  "expanded_requirements": [
    {{
      "id": "req-0001",
      "priority": "must|should|could|wont",
      "description": "...",
      "source": "user|inferred|research|memory|decision",
      "acceptance": []
    }}
  ],
  "target_outputs": [],
  "definition_of_done": [],
  "verification_strategy": [],
  "budget": {{
    "max_iterations": 8,
    "max_model_calls": 60
  }}
}}"""
