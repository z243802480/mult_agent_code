from pathlib import Path

import pytest

from asteria_runtime.agents.brainstorm_agent import BrainstormAgent
from asteria_runtime.agents.research_agent import ResearchAgent
from asteria_runtime.models.base import ChatRequest
from asteria_runtime.storage.schema_validator import SchemaValidator


class RaisingCaptureClient:
    def __init__(self) -> None:
        self.request: ChatRequest | None = None

    def chat(self, request: ChatRequest):
        self.request = request
        raise RuntimeError("stop after capture")


def test_brainstorm_agent_request_uses_role_contract() -> None:
    client = RaisingCaptureClient()
    agent = BrainstormAgent(client, SchemaValidator(Path("schemas")))

    with pytest.raises(RuntimeError, match="stop after capture"):
        agent.generate("explore options", {"project": {}}, "run-1")

    assert client.request is not None
    assert client.request.metadata["agent_id"] == "BrainstormAgent"
    assert client.request.metadata["agent_role_contract"]["role"] == "BrainstormAgent"
    assert client.request.metadata["agent_role_contract"]["purpose"] == "brainstorming"


def test_research_agent_request_uses_role_contract() -> None:
    client = RaisingCaptureClient()
    agent = ResearchAgent(client, SchemaValidator(Path("schemas")))

    with pytest.raises(RuntimeError, match="stop after capture"):
        agent.synthesize("summarize", [], "run-1")

    assert client.request is not None
    assert client.request.metadata["agent_id"] == "ResearchAgent"
    assert client.request.metadata["agent_role_contract"]["role"] == "ResearchAgent"
    assert client.request.metadata["agent_role_contract"]["purpose"] == "research"
