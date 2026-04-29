from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.agents.execution_action import normalize_execution_action
from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class DebugAgentError(RuntimeError):
    pass


@dataclass
class DebugAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def propose_repair(
        self,
        task: dict,
        goal_spec: dict,
        failure_evidence: dict,
        available_tools: list[str],
        run_id: str,
        runtime_context: dict | None = None,
    ) -> dict:
        request = ChatRequest(
            purpose="task_repair",
            model_tier="medium",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(
                    role="user",
                    content=self._user_prompt(
                        task,
                        goal_spec,
                        failure_evidence,
                        available_tools,
                        runtime_context or {},
                    ),
                ),
            ],
            response_format="json",
            temperature=0.15,
            max_output_tokens=5000,
            metadata={"run_id": run_id, "agent_id": "DebugAgent", "task_id": task["task_id"]},
        )
        response = self.model_client.chat(request)
        action = self._parse_json(response.content)
        action = normalize_execution_action(action, task)
        if action.get("task_id") != task["task_id"]:
            raise DebugAgentError(f"Repair task_id mismatch: {action.get('task_id')} != {task['task_id']}")
        try:
            self.validator.validate("execution_action", action)
        except SchemaValidationError as exc:
            raise DebugAgentError(f"Repair action failed schema validation: {exc}") from exc
        return action

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise DebugAgentError(f"Repair response was not valid JSON: {exc}") from exc
        return parsed

    def _system_prompt(self) -> str:
        return """You are DebugAgent in a local-first autonomous development runtime.

Return only valid JSON matching the ExecutionAction schema. Do not wrap in markdown.

You must:
- Diagnose the blocked task using the supplied failure evidence.
- Propose the smallest repair that can plausibly satisfy the task acceptance criteria.
- Use only tools from allowed_tools and available_tools.
- Prefer editing the existing broken artifact instead of rewriting unrelated files.
- Include verification calls that directly prove the repair.
- Use cross-platform Python commands for verification; do not rely on Unix-only commands like cat, wc, grep, or sed.
- If a verification command is expected to return a non-zero code, pass expected_returncodes in run_command args.
- Avoid destructive commands, network calls, deployment, or secret access.
"""

    def _user_prompt(
        self,
        task: dict,
        goal_spec: dict,
        failure_evidence: dict,
        available_tools: list[str],
        runtime_context: dict,
    ) -> str:
        payload = {
            "task": task,
            "goal_spec": goal_spec,
            "failure_evidence": failure_evidence,
            "runtime_context": runtime_context,
            "available_tools": available_tools,
            "allowed_tools": task["allowed_tools"],
            "output_schema": {
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": "short repair summary",
                "tool_calls": [
                    {
                        "tool_name": "apply_patch",
                        "args": {"patch": "--- a/file.py\n+++ b/file.py\n..."},
                        "reason": "minimal repair",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -m pytest",
                            "expected_returncodes": [0],
                        },
                        "reason": "verify repair; use expected_returncodes for expected non-zero CLI usage checks",
                    }
                ],
                "completion_notes": "what was repaired",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
