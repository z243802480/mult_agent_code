from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.json_extractor import JsonExtractionError, parse_json_object
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
        data = self._normalize(data, goal)
        try:
            self.validator.validate("goal_spec", data)
        except SchemaValidationError as exc:
            raise GoalSpecError(f"GoalSpec failed schema validation: {exc}") from exc
        return data

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise GoalSpecError(f"GoalSpec response was not valid JSON: {exc}") from exc
        return parsed

    def _normalize(self, data: dict, original_goal: str) -> dict:
        normalized = dict(data)
        normalized["schema_version"] = str(normalized.get("schema_version") or "0.1.0")
        normalized["goal_id"] = str(normalized.get("goal_id") or "goal-0001")
        normalized["original_goal"] = str(normalized.get("original_goal") or original_goal)
        normalized["normalized_goal"] = str(normalized.get("normalized_goal") or original_goal)
        normalized["goal_type"] = self._goal_type(str(normalized.get("goal_type") or "unknown"))
        for key in [
            "assumptions",
            "constraints",
            "non_goals",
            "target_outputs",
            "definition_of_done",
            "verification_strategy",
        ]:
            normalized[key] = self._string_list(normalized.get(key))
        normalized["expanded_requirements"] = self._requirements(
            normalized.get("expanded_requirements"),
            normalized["normalized_goal"],
        )
        budget = normalized.get("budget")
        normalized["budget"] = budget if isinstance(budget, dict) else {}
        return normalized

    def _requirements(self, value: object, fallback_description: str) -> list[dict]:
        items = value if isinstance(value, list) else []
        requirements: list[dict] = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                requirement = dict(item)
            else:
                requirement = {"description": self._stringify(item)}
            requirement["id"] = str(requirement.get("id") or f"req-{index:04d}")
            requirement["priority"] = self._priority(str(requirement.get("priority") or "must"))
            requirement["description"] = str(
                requirement.get("description") or fallback_description
            )
            requirement["source"] = self._source(str(requirement.get("source") or "inferred"))
            requirement["acceptance"] = self._string_list(requirement.get("acceptance"))
            if not requirement["acceptance"]:
                requirement["acceptance"] = ["Requirement is implemented and verified"]
            requirements.append(requirement)
        if requirements:
            return requirements
        return [
            {
                "id": "req-0001",
                "priority": "must",
                "description": fallback_description,
                "source": "inferred",
                "acceptance": ["Goal has a verifiable first implementation slice"],
            }
        ]

    def _string_list(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._stringify(item) for item in value if self._stringify(item)]
        return [self._stringify(value)]

    def _stringify(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ["path", "name", "type", "title", "description", "value"]:
                item = value.get(key)
                if item:
                    return str(item).strip()
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value).strip()

    def _priority(self, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in {"must", "should", "could", "wont"} else "must"

    def _source(self, value: str) -> str:
        normalized = value.strip().lower()
        return (
            normalized
            if normalized in {"user", "inferred", "research", "memory", "decision"}
            else "inferred"
        )

    def _goal_type(self, value: str) -> str:
        normalized = value.strip().lower()
        return (
            normalized
            if normalized
            in {
                "software_tool",
                "codebase_improvement",
                "research",
                "report",
                "knowledge_base",
                "automation",
                "unknown",
            }
            else "unknown"
        )

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
