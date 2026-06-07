from __future__ import annotations

import json
from typing import Any


def resolve_worker_transport(
    *,
    policy: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    for source in (
        (runtime_context or {}).get("agent_role_contract"),
        (policy or {}).get("agent_loop"),
    ):
        if not isinstance(source, dict):
            continue
        value = str(source.get("worker_transport") or "").strip().lower()
        if value in {"json", "tool_use"}:
            return value
    return "json"


def tool_definitions_for(available_tools: list[str]) -> list[dict[str, Any]]:
    specs = {
        "write_file": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write or overwrite a workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "read_file": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        "run_command": {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a bounded shell command for verification.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "expected_returncodes": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        "run_tests": {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Run pytest or similar test command.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "expected_returncodes": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": ["command"],
                },
            },
        },
    }
    return [specs[name] for name in available_tools if name in specs]


def extract_tool_calls(raw_response: dict[str, Any]) -> list[dict[str, Any]]:
    message = _first_message(raw_response)
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        args_raw = function.get("arguments") or "{}"
        if isinstance(args_raw, dict):
            args = args_raw
        else:
            try:
                args = json.loads(str(args_raw))
            except json.JSONDecodeError:
                args = {}
        normalized.append(
            {
                "tool_name": name,
                "args": args if isinstance(args, dict) else {},
                "reason": "provider native tool_use",
            }
        )
    return normalized


def execution_action_from_tool_calls(
    *,
    task: dict[str, Any],
    run_id: str,
    sequence: int,
    tool_calls: list[dict[str, Any]],
    summary: str = "tool_use execution",
) -> dict[str, Any]:
    primary = tool_calls[0] if tool_calls else None
    capability_name = str((primary or {}).get("tool_name") or "write_file")
    return {
        "schema_version": "0.1.0",
        "task_id": task["task_id"],
        "summary": summary,
        "tool_calls": tool_calls,
        "verification": [],
        "runtime_requests": [],
        "completion_notes": "Generated from provider tool_use transport.",
        "agent_loop_decision": {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "sequence": sequence,
            "next_action": {
                "action": "tool",
                "reason": "Native tool_use transport selected structured tool calls.",
                "target_task_id": task["task_id"],
                "capability_ref": {"type": "tool", "name": capability_name},
                "expected_observation": {"summary": "Tool observation should confirm the call."},
                "risk": "medium",
                "budget_hint": {"model_calls": 1, "tool_budget_units": len(tool_calls)},
                "evidence_refs": [],
            },
        },
    }


def _first_message(raw_response: dict[str, Any]) -> dict[str, Any] | None:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    return message if isinstance(message, dict) else None
