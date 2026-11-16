"""Validate an exact execution-consent proposal without executing or granting it."""


def requested_execution(value: dict) -> tuple[str, dict, str]:
    tool = value.get("tool_name")
    args = value.get("args")
    reason = value.get("reason")
    if tool not in {"run_command", "run_tests"} or not isinstance(args, dict):
        raise ValueError("Request a concrete run_command or run_tests with an args object")
    allowed = {"command", "timeout_seconds"} | ({"expected_returncodes"} if tool == "run_command" else set())
    if set(args) - allowed or not isinstance(args.get("command"), str) or not args["command"].strip():
        raise ValueError("Use the exact supported execution args, including a nonempty command")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Explain why this exact action needs authorization")
    return tool, dict(args), reason
