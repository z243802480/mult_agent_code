from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.orchestration_dynamic_live import execute_verifier_fanout_live
from asteria_runtime.core.orchestration_dynamic_live_provider import (
    LIVE_PROVIDER_POLICY_KEY,
    live_provider_enabled,
    record_live_provider_touch,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeCheapClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="readonly scope confirmed",
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-cheap",
            raw_response={},
        )


def test_live_provider_disabled_by_default() -> None:
    assert live_provider_enabled({}) is False
    assert live_provider_enabled({"agent_loop": {LIVE_PROVIDER_POLICY_KEY: False}}) is False


def test_live_provider_touch_records_model_call(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-provider-touch"
    run_dir.mkdir(parents=True, exist_ok=True)
    policy = {"agent_loop": {LIVE_PROVIDER_POLICY_KEY: True}}
    touch = record_live_provider_touch(
        run_dir=run_dir,
        validator=validator,
        task_id="v1",
        purpose="test",
        policy=policy,
        model_client=FakeCheapClient(),
    )
    assert touch["model_calls"] == 1
    assert touch["provider"] == "fake"


def test_verifier_live_includes_provider_model_calls(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-verifier-provider"
    policy = {"agent_loop": {LIVE_PROVIDER_POLICY_KEY: True}, "protected_paths": []}

    from asteria_runtime.core import orchestration_dynamic_live_provider as provider_module

    monkeypatch.setattr(provider_module, "create_model_client", lambda *_args, **_kwargs: FakeCheapClient())

    result = execute_verifier_fanout_live(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-verifier-provider",
        validator=validator,
        tasks=[{"task_id": "v1", "verdict": "pass"}],
        parent_task_id="probe:verify:adversarial",
        policy=policy,
    )
    assert result["ok"] is True
    assert result["variables"]["provider_model_calls"] >= 1
