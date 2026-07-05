"""End-to-end: a model-run shell command cannot read the harness's provider credentials.

This is the real proof of the footgun fix — not that a helper filters a dict, but that the actual
`run_command` execution path spawns a child whose environment has the secret removed, even when the
command is an interpreter one-liner that the static ShellGuard denylist cannot inspect.
"""
from pathlib import Path

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.command_tools import RunCommandTool

_SECRET_VALUE = "sk-supersecret-DO-NOT-LEAK-2026"


def _policy() -> dict:
    return {
        "budgets": {
            "max_model_calls_per_goal": 60,
            "max_tool_calls_per_goal": 20,
            "max_total_minutes_per_goal": 30,
            "max_iterations_per_goal": 8,
            "max_repair_attempts_total": 5,
            "max_repair_attempts_per_task": 2,
            "max_replans_per_task": 2,
            "max_research_calls": 5,
            "max_user_decisions": 5,
        },
        "permissions": {
            "allow_network": False,
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_secret_file_read": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        },
        "protected_paths": [".env", "secrets/", ".git/"],
    }


def _context(tmp_path: Path) -> RuntimeContext:
    run_id = "run-20260705-0001"
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True)
    validator = SchemaValidator(Path("schemas"))
    return RuntimeContext(
        root=tmp_path,
        run_id=run_id,
        policy=_policy(),
        validator=validator,
        budget=BudgetController(_policy(), run_id=run_id),
    )


def test_interpreter_payload_cannot_read_provider_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_API_KEY", _SECRET_VALUE)
    monkeypatch.setenv("PLAIN_TASK_VAR", "harmless-value")
    ctx = _context(tmp_path)
    tool = RunCommandTool(default_timeout_seconds=15)

    # An interpreter payload — exactly the residual the ShellGuard denylist admits it cannot inspect.
    result = tool.run(
        ctx,
        command=(
            "python -c \"import os;"
            "print('KEY=' + os.environ.get('AGENT_MODEL_API_KEY','<absent>'));"
            "print('PLAIN=' + os.environ.get('PLAIN_TASK_VAR','<absent>'))\""
        ),
    )

    assert result.ok, result.data
    stdout = result.data["stdout"]
    # The secret value must never appear in output the model would see.
    assert _SECRET_VALUE not in stdout
    assert "KEY=<absent>" in stdout
    # Non-credential vars are preserved so ordinary tasks still work.
    assert "PLAIN=harmless-value" in stdout
