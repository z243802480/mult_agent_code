from __future__ import annotations

import json
from typing import Any


def resolve_worker_transport(
    *,
    policy: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
) -> str:
    for source in (
        _transport_hint_from_task(task),
        _transport_hint_from_runtime_context(runtime_context),
    ):
        if source:
            return source
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


def _transport_hint_from_task(task: dict[str, Any] | None) -> str | None:
    if not isinstance(task, dict):
        return None
    return _transport_hint_from_mapping(task.get("runtime_profile_hints"))


def _transport_hint_from_runtime_context(runtime_context: dict[str, Any] | None) -> str | None:
    if not isinstance(runtime_context, dict):
        return None
    return _transport_hint_from_mapping(runtime_context.get("runtime_profile_hints"))


def _transport_hint_from_mapping(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    transport = str(value.get("worker_transport") or "").strip().lower()
    if transport in {"json", "tool_use"}:
        return transport
    return None


def tool_definitions_for(
    available_tools: list[str],
    extra_specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
    native = [specs[name] for name in available_tools if name in specs]
    if extra_specs:
        native.extend(extra_specs)
    return native


def native_tool_specs_from_surface(
    model_tool_surface: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """OpenAI-style native function specs for task-allowed mcp__/skill__ surface tools.

    Returns [] when the surface is missing or carries no external/skill tools, so the
    default json path and the no-MCP/no-skill path stay byte-for-byte unchanged. This is
    pure exposure under the tool_use transport — execution still routes through the gateway
    by tool name (ADR-0014/0015), and allow/ask/deny stays at the call boundary.
    """
    if not isinstance(model_tool_surface, dict):
        return []
    specs: list[dict[str, Any]] = []
    for tool in model_tool_surface.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        if not name.startswith(("mcp__", "skill__")):
            continue
        if not tool.get("task_allowed"):
            continue
        contract = tool.get("parameter_contract")
        parameters = (
            contract
            if isinstance(contract, dict) and contract
            else {"type": "object", "properties": {}}
        )
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": parameters,
                },
            }
        )
    return specs


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
    work_calls, verification_calls = _split_execution_and_verification_calls(tool_calls)
    primary = (work_calls or verification_calls or [None])[0]
    capability_name = str((primary or {}).get("tool_name") or "write_file")
    return {
        "schema_version": "0.1.0",
        "task_id": task["task_id"],
        "summary": summary,
        "tool_calls": work_calls,
        "verification": verification_calls,
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


def _split_execution_and_verification_calls(
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    work_calls: list[dict[str, Any]] = []
    verification_calls: list[dict[str, Any]] = []
    saw_mutation = False
    for call in tool_calls:
        tool_name = str(call.get("tool_name") or "")
        if tool_name in {"write_file", "apply_patch"}:
            saw_mutation = True
            work_calls.append(call)
            continue
        if saw_mutation and tool_name in {"run_command", "run_tests"}:
            verification_calls.append(call)
            continue
        work_calls.append(call)
    return work_calls, verification_calls


def _first_message(raw_response: dict[str, Any]) -> dict[str, Any] | None:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    return message if isinstance(message, dict) else None
