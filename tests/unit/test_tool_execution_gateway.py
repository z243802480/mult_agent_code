from pathlib import Path

import pytest

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeRegistry:
    def call(self, tool_name: str, _context: RuntimeContext, **kwargs: object) -> object:
        return FakeResult(
            ok=bool(kwargs.get("ok", True)),
            summary=str(kwargs.get("summary", f"called {tool_name}")),
            error=kwargs.get("error") if isinstance(kwargs.get("error"), str) else None,
            data=kwargs.get("data") if isinstance(kwargs.get("data"), dict) else {},
        )


class FakeResult:
    def __init__(
        self,
        *,
        ok: bool,
        summary: str,
        error: str | None = None,
        data: dict | None = None,
    ) -> None:
        self.ok = ok
        self.summary = summary
        self.error = error
        self.data = data or {}


def test_tool_gateway_rejects_disallowed_tool(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    with pytest.raises(PermissionError, match="Tool is not allowed"):
        gateway.run_tool_calls(
            [{"tool_name": "write_file", "args": {}}],
            {"task_id": "task-0001", "allowed_tools": []},
            context,
        )


def test_tool_gateway_accepts_expected_diagnostic_failure(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    task = {
        "task_id": "task-0001",
        "allowed_tools": ["run_command"],
        "completion_contract": {"allows_expected_failure": True},
    }

    results = gateway.run_tool_calls(
        [{"tool_name": "run_command", "args": {"ok": False, "error": "nonzero_exit"}}],
        task,
        context,
    )

    assert results[0].ok is True
    assert results[0].summary.startswith("Diagnostic failure accepted")


def _gateway(tmp_path: Path) -> tuple[ToolExecutionGateway, RuntimeContext]:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    return ToolExecutionGateway(FakeRegistry(), ToolPermissionPolicy(tmp_path, validator)), context
