from __future__ import annotations

import json
from dataclasses import dataclass

from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class GoalSpecError(RuntimeError):
    pass


@dataclass
class GoalSpecAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def generate(
        self,
        goal: str,
        project_context: dict,
        run_id: str,
        model_tier: str = "strong",
    ) -> dict:
        parse_error: GoalSpecError | None = None
        role_contract = role_contract_for(
            role="GoalSpecAgent",
            purpose="goal_spec",
            policy=project_context.get("policy") if isinstance(project_context.get("policy"), dict) else None,
        )
        request = ChatRequest(
            purpose="goal_spec",
            model_tier=model_tier,
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=self._user_prompt(goal, project_context)),
            ],
            response_format="json",
            temperature=0.2,
            max_output_tokens=4000,
            metadata={
                "run_id": run_id,
                "agent_id": "GoalSpecAgent",
                "agent_role_contract": role_contract.to_dict(),
                "model_route": (project_context.get("runtime_context") or {}).get("goal_spec_route_plan")
                if isinstance(project_context.get("runtime_context"), dict)
                else None,
            },
        )
        response = self.model_client.chat(request)
        try:
            data = self._parse_json(response.content)
        except GoalSpecError as exc:
            parse_error = exc
            data = self._fallback_goal_spec(goal, str(exc))
        data = self._normalize(data, goal)
        if parse_error:
            data["assumptions"].append(
                "Model returned non-JSON for GoalSpec; deterministic goal specification fallback was used."
            )
        try:
            self.validator.validate("goal_spec", data)
        except SchemaValidationError as exc:
            data = self._fallback_goal_spec(goal, f"schema validation failed: {exc}")
            data["assumptions"].append(
                "Model GoalSpec shape could not be repaired safely; deterministic fallback was used."
            )
            self.validator.validate("goal_spec", data)
        return data

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise GoalSpecError(f"GoalSpec response was not valid JSON: {exc}") from exc
        return parsed

    def _fallback_goal_spec(self, goal: str, reason: str) -> dict:
        return {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": goal,
            "goal_type": "software_tool",
            "assumptions": [
                "The goal should be handled as a small local-first implementation slice.",
                f"Fallback reason: {reason}",
            ],
            "constraints": [
                "Keep the implementation local.",
                "Avoid protected paths and destructive shell actions.",
            ],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": goal,
                    "source": "user",
                    "acceptance": [
                        "The requested local artifact or behavior is created.",
                        "A local verification command or observable file check passes.",
                    ],
                }
            ],
            "target_outputs": [],
            "definition_of_done": [
                "Requested local artifact or behavior exists.",
                "Verification evidence is recorded.",
            ],
            "verification_strategy": ["Run the smallest local verification for the requested output."],
            "budget": {
                "max_iterations": 3,
                "max_model_calls": 12,
            },
        }

    def _normalize(self, data: dict, original_goal: str) -> dict:
        normalized = dict(data)
        normalized["schema_version"] = str(normalized.get("schema_version") or "0.1.0")
        normalized["goal_id"] = str(normalized.get("goal_id") or "goal-0001")
        normalized["original_goal"] = original_goal
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
