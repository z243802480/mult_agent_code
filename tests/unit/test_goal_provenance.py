import json
from copy import deepcopy
from pathlib import Path

import pytest

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.core.goal_provenance import proposal_origin_status
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_goal_spec_agent import FakeClient, valid_goal_spec_json


def test_runtime_binds_interpretation_without_promoting_source_claims():
    proposal = json.loads(valid_goal_spec_json())
    proposal["proposal_origin"] = {"producer": "user", "kind": "approved"}
    proposal["constraints"] = ["Model-added restriction"]
    proposal["expanded_requirements"][0]["source"] = "user"
    goal = GoalSpecAgent(FakeClient(json.dumps(proposal)), SchemaValidator(Path("schemas"))).generate(
        "Create a local artifact", {}, "run-origin",
    )
    assert goal["original_goal"] == "Create a local artifact"
    assert goal["constraints"] == ["Model-added restriction"]  # Not silently edited away.
    assert goal["proposal_origin"]["producer"] == "goal_spec_agent"
    assert goal["proposal_origin"]["kind"] == "model_proposal"
    assert proposal_origin_status(goal) == "verified"
    assert goal["expanded_requirements"][0]["source"] == "user"  # A model claim, not authentication.


@pytest.mark.parametrize("field", ["original_goal", "constraints", "expanded_requirements", "edit_boundary"])
def test_changed_goal_interpretations_lose_binding(field):
    goal = GoalSpecAgent(FakeClient(valid_goal_spec_json()), SchemaValidator(Path("schemas"))).generate(
        "Create a local artifact", {}, "run-origin",
    )
    changed = deepcopy(goal)
    changed[field] = "changed" if field == "original_goal" else []
    assert proposal_origin_status(changed) == "unverified"
    changed.pop("proposal_origin")
    assert proposal_origin_status(changed) == "unverified"


def test_goal_fallback_is_labeled_separately_and_still_validated():
    goal = GoalSpecAgent(FakeClient("not JSON"), SchemaValidator(Path("schemas"))).generate(
        "Create a local artifact", {}, "run-origin",
    )
    assert goal["proposal_origin"]["kind"] == "runtime_fallback"
    assert proposal_origin_status(goal) == "verified"
    assert goal["edit_boundary"] == {"mode": "restricted", "paths": []}


def test_goal_understanding_receives_loaded_guidance_and_required_commands():
    client = FakeClient(valid_goal_spec_json())
    guidance = {"path": "AGENTS.md", "content": "Do not generate caches.", "truncated": False}
    GoalSpecAgent(client, SchemaValidator(Path("schemas"))).generate("Create an artifact", {
        "runtime_context": {"root_guidance": guidance, "project_commands": {"test": "required-check"}},
    }, "run-origin")
    prompt = client.requests[0].messages[1].content
    context = json.loads(prompt.split("Project context:\n", 1)[1].split("\n\nReturn this exact JSON shape:", 1)[0])
    assert context["runtime_context"]["root_guidance"] == guidance
    assert context["runtime_context"]["project_commands"] == {"test": "required-check"}
