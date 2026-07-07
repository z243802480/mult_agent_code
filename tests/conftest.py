import os

import pytest


@pytest.fixture(autouse=True)
def pin_legacy_fsm_default(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """RA7 bridge — the production default for ``agent_loop.model_driven_turn`` was flipped to
    ``True`` (立真身 / model-driven single-loop spine is now the coding brain; ADR-0016 §1).

    The large legacy suite below predates the flip: its fake clients speak the FSM ``ExecutionAction``
    JSON and its assertions inspect FSM-only artifacts (agent_loop_decisions/observations/execution
    results, next_action dispatch, auto-repair/replan rounds, probe scaffolding). Those tests exercise
    the FSM path, which STILL EXISTS and is still reachable via an explicit ``model_driven_turn=False``
    (the flag's reversibility contract). So we pin them to the *prior* default (``False``) — byte-identical
    to their pre-flip behaviour — rather than rewrite them here. RA7b deletes the FSM code and these
    tests together.

    Tests marked ``@pytest.mark.spine_default`` opt out and see the REAL flipped default, so the flip
    itself is locked by tests that do no mocking of the enablement path. Tests that set
    ``model_driven_turn`` explicitly in their policy are unaffected either way.
    """
    if request.node.get_closest_marker("spine_default"):
        return

    def _enabled_prior_default(_self: object, policy: dict) -> bool:
        raw_agent_loop = policy.get("agent_loop")
        agent_loop = raw_agent_loop if isinstance(raw_agent_loop, dict) else {}
        return bool(agent_loop.get("model_driven_turn", False))

    monkeypatch.setattr(
        "asteria_runtime.commands.execute_command.ExecuteCommand._model_driven_turn_enabled",
        _enabled_prior_default,
    )


@pytest.fixture(autouse=True)
def isolate_model_route_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    prefixes = [
        "AGENT_MODEL",
        "AGENT_MODEL_STRONG",
        "AGENT_MODEL_MEDIUM",
        "AGENT_MODEL_CHEAP",
    ]
    keys = [
        "PROVIDER",
        "BASE_URL",
        "NAME",
        "API_KEY",
        "TIMEOUT_SECONDS",
        "MAX_RETRIES",
        "STREAMING",
        "STREAM_IDLE_TIMEOUT_SECONDS",
    ]
    for prefix in prefixes:
        for key in keys:
            monkeypatch.delenv(f"{prefix}_{key}", raising=False)
    for name in [
        "ASTERIA_HOME",
        "OPENAI_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
        "GLM_API_KEY",
        "ZAI_API_KEY",
        "ZHIPU_API_KEY",
        "BIGMODEL_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("ASTERIA_HOME", str(tmp_path / "asteria-home"))

    # Keep unrelated environment stable; only model routing and provider credentials
    # are isolated so tests cannot accidentally hit a real endpoint.
    for name in list(os.environ):
        if name.startswith("AGENT_MODEL_") and name not in {
            f"{prefix}_{key}" for prefix in prefixes for key in keys
        }:
            monkeypatch.delenv(name, raising=False)
