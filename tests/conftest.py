import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # RA7b slice3f deleted the FSM round loop; the model-driven spine (ADR-0016 §1) is the sole
    # execution path. The old RA7 bridge fixture (pinned legacy-FSM tests to model_driven_turn=False)
    # and its `@pytest.mark.spine_default` opt-out are retired together with the FSM code. The marker
    # is now a no-op — every test runs on the spine — registered here so the historical usages do not
    # warn; the markers themselves are swept in a follow-up cleanup.
    config.addinivalue_line(
        "markers",
        "spine_default: (retired no-op) test runs on the model-driven spine (formerly opted out of the FSM bridge)",
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
