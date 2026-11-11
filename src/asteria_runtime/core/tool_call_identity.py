"""Invocation identity is independent of ledger layout, process lifetime and ordering."""

from uuid import uuid4


def new_tool_call_id() -> str:
    return f"toolcall-{uuid4().hex}"
