"""Validate an exact execution-consent proposal without executing or granting it."""


def execution_args_schema(tool_name: str) -> dict:
    """Describe exactly the execution keys the consent boundary accepts."""
    properties = {"command": {"type": "string", "minLength": 1},
                  "timeout_seconds": {"type": "number", "exclusiveMinimum": 0}}
    if tool_name == "run_command":
        properties["expected_returncodes"] = {"type": "array", "items": {"type": "integer"}}
    elif tool_name != "run_tests":
        raise ValueError("Consent supports run_command or run_tests")
    return {"type": "object", "properties": properties, "required": ["command"], "additionalProperties": False}


def requested_execution(value: dict) -> tuple[str, dict, str]:
    tool = value.get("tool_name")
    args = value.get("args")
    reason = value.get("reason")
    if tool not in {"run_command", "run_tests"} or not isinstance(args, dict):
        raise ValueError("Request a concrete run_command or run_tests with an args object")
    allowed = set(execution_args_schema(tool)["properties"])
    unsupported = set(args) - allowed
    if unsupported:
        names = ", ".join(str(name)[:80] for name in sorted(unsupported, key=str)[:8])
        raise ValueError(f"Unsupported execution args for {tool}: {names}. "
                         f"Supported keys: {', '.join(sorted(allowed))}; args were not changed")
    if not isinstance(args.get("command"), str) or not args["command"].strip():
        raise ValueError("args.command must be a nonempty exact command string")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Explain why this exact action needs authorization")
    return tool, dict(args), reason
