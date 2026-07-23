"""create_recap_client mints a best-effort recap client only when a real provider is reachable.

Root cause it guards against: the CLI/Studio path builds RunCommand without injecting model
clients (execution creates its own run-scoped client), so the closing recap always no-opped and
every real run fell back to the robotic status-line conclusion. create_recap_client gives the
recap its own client WITHOUT touching the execution path — but must return None on a fake/offline
tier so an air-gapped run keeps its clean structured fallback instead of surfacing canned text.
"""
from pathlib import Path

import pytest

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.factory import create_recap_client, real_route_for_tier
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator

_MODEL_ENV = [
    "AGENT_MODEL_PROVIDER",
    "AGENT_MODEL_API_KEY",
    "AGENT_MODEL_BASE_URL",
    "AGENT_MODEL_NAME",
    "AGENT_MODEL_STRONG_PROVIDER",
    "AGENT_MODEL_MEDIUM_PROVIDER",
    "AGENT_MODEL_MEDIUM_NAME",
    "AGENT_MODEL_CHEAP_PROVIDER",
    "ZHIPU_API_KEY",
    "BIGMODEL_API_KEY",
    "ZAI_API_KEY",
    "GLM_API_KEY",
]


@pytest.fixture(autouse=True)
def clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _MODEL_ENV:
        monkeypatch.delenv(key, raising=False)


def _validator() -> SchemaValidator:
    return SchemaValidator(Path("schemas"))


def test_offline_tier_returns_none_so_fallback_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake-only run (tests, air-gapped default): no recap client, so the caller keeps its clean
    # structured conclusion rather than a canned fake recap.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "fake")
    assert real_route_for_tier("medium") is None
    assert create_recap_client(None, _validator(), tier="medium") is None


def test_real_tier_mints_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real provider on the recap tier → a usable client (not the fake), so the recap actually runs.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "qwen2.5-coder:7b")
    route = real_route_for_tier("medium")
    assert route is not None and route.provider == "ollama"
    client = create_recap_client(None, _validator(), tier="medium")
    assert client is not None
    assert not isinstance(client, FakeModelClient)


def test_tier_with_real_default_but_fake_medium_still_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # The medium tier is what the recap uses; a real default must not mask a fake medium tier.
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "fake")
    assert real_route_for_tier("medium") is None
    assert create_recap_client(None, _validator(), tier="medium") is None


def test_budget_is_threaded_into_the_minted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: create_recap_client used to drop the caller's budget entirely, so every recap
    # call was logged to model_calls.jsonl (the client's ModelCallLogger always fires) but never
    # counted against cost_report.json's model_calls tally, desyncing the two on every completed
    # run. The client must carry the SAME BudgetController the caller passed in.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "qwen2.5-coder:7b")
    budget = BudgetController(policy={}, run_id="run-test")
    client = create_recap_client(None, _validator(), tier="medium", budget=budget)
    assert client is not None
    medium_client = client.tier_clients["medium"]  # type: ignore[attr-defined]
    assert medium_client.budget is budget
