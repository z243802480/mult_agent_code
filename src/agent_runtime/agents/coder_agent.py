from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class CoderAgentError(RuntimeError):
    pass


@dataclass
class CoderAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def propose_action(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        run_id: str,
        runtime_context: dict | None = None,
    ) -> dict:
        request = ChatRequest(
            purpose="task_execution",
            model_tier="medium",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(
                    role="user",
                    content=self._user_prompt(
                        task,
                        goal_spec,
                        project_config,
                        available_tools,
                        runtime_context or {},
                    ),
                ),
            ],
            response_format="json",
            temperature=0.2,
            max_output_tokens=5000,
            metadata={"run_id": run_id, "agent_id": "CoderAgent", "task_id": task["task_id"]},
        )
        response = self.model_client.chat(request)
        action = self._parse_json(response.content)
        if action.get("task_id") != task["task_id"]:
            raise CoderAgentError(
                f"ExecutionAction task_id mismatch: {action.get('task_id')} != {task['task_id']}"
            )
        try:
            self.validator.validate("execution_action", action)
        except SchemaValidationError as exc:
            raise CoderAgentError(f"ExecutionAction failed schema validation: {exc}") from exc
        return action

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise CoderAgentError(f"ExecutionAction response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise CoderAgentError("ExecutionAction response must be a JSON object")
        return parsed

    def _system_prompt(self) -> str:
        return """You are CoderAgent in a local-first autonomous development runtime.

Return only valid JSON matching the ExecutionAction schema. Do not wrap in markdown.

You must:
- Make a small, verifiable change for the assigned task.
- Use only tools from allowed_tools and available_tools.
- Prefer apply_patch for editing existing files and write_file for new files.
- Include verification tool calls when possible.
- Avoid destructive commands, global installs, deployment, or network calls unless explicitly allowed.
- Keep the implementation practical and production-oriented; do not create placeholder-only files.
"""

    def _user_prompt(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        runtime_context: dict,
    ) -> str:
        payload = {
            "task": task,
            "goal_spec": goal_spec,
            "project": project_config,
            "runtime_context": runtime_context,
            "available_tools": available_tools,
            "allowed_tools": task["allowed_tools"],
            "output_schema": {
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": "short execution summary",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "example.txt", "content": "...", "overwrite": True},
                        "reason": "why this call is needed",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_tests",
                        "args": {},
                        "reason": "verify the change",
                    }
                ],
                "completion_notes": "what should be true after execution",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
