import json
from pathlib import Path

import pytest

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_goal_spec_agent import FakeClient, valid_goal_spec_json


@pytest.mark.parametrize("declared", [True, False])
def test_goal_prompt_exposes_content_contract_and_keeps_legacy_responses_valid(declared):
    proposal = json.loads(valid_goal_spec_json())
    constraint = [{"path": "docs/guide.md", "mode": "existing_lines"}]
    if declared:
        proposal["content_preservation"] = constraint
    client = FakeClient(json.dumps(proposal))
    result = GoalSpecAgent(client, SchemaValidator(Path("schemas"))).generate(
        "Add a section to docs/guide.md preserving every existing line.", {"project": {}}, "run-1",
    )
    # The declared response surface must agree with the system's supported contract.
    template = json.loads(client.requests[0].messages[1].content.split("Return this exact JSON shape:\n", 1)[1])
    assert template["content_preservation"] == []
    assert result.get("content_preservation") == (constraint if declared else None)
    assert len(client.requests) == 1  # Old valid plans are not forced through protocol retries.
