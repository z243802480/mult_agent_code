from copy import deepcopy
import json
from pathlib import Path

import pytest

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.core.verification_revision import method_provenance, model_strategy_origin
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_goal_spec_agent import FakeClient, valid_goal_spec_json
from tests.unit.test_verification_revision import ARGS, NEW, OLD, REQUIRED, run_commands, setup_run


def generated_goal(original=None):
    proposal = json.loads(valid_goal_spec_json())
    proposal["verification_strategy"] = [OLD, REQUIRED]
    # A provider may return arbitrary labels; the trusted producer replaces them.
    proposal["verification_strategy_origin"] = {"producer": "user", "revisable": True}
    client = FakeClient(json.dumps(proposal))
    goal = GoalSpecAgent(client, SchemaValidator(Path("schemas"))).generate(
        original or f"Create the artifact and preserve {REQUIRED}", {}, "run-1",
    )
    assert len(client.requests) == 1
    return goal


def test_runtime_records_actual_strategy_origin_without_granting_user_check_revision():
    goal = generated_goal()
    assert goal["verification_strategy_origin"] == model_strategy_origin(goal)
    source = method_provenance([OLD, REQUIRED, f"cd . && {REQUIRED}"], goal, {
        "root_guidance": {}, "project_commands": {},
    })
    assert source["revisable_commands"] == [OLD]


@pytest.mark.parametrize("case", [
    "legacy", "bad_digest", "changed_goal", "changed_strategy", "user_required",
    "project_required", "guidance_required", "wrapper", "other_requirement",
    "user_wrapper", "project_wrapper", "guidance_wrapper",
])
def test_missing_or_changed_origin_never_relaxes_higher_authority(case):
    goal = generated_goal(f"Preserve {OLD}" if case.startswith("user_") else None)
    runtime = {"root_guidance": {}, "project_commands": {}}
    command = OLD
    if case == "legacy":
        goal.pop("verification_strategy_origin")
    elif case == "bad_digest":
        goal["verification_strategy_origin"]["strategy_sha256"] = "0" * 64
    elif case == "changed_goal":
        goal["original_goal"] += "Changed authorization."
    elif case == "changed_strategy":
        goal["verification_strategy"].append(NEW)
    elif case in {"project_required", "project_wrapper"}:
        runtime["project_commands"] = {"test": OLD}
    elif case in {"guidance_required", "guidance_wrapper"}:
        runtime["root_guidance"] = {"content": OLD, "truncated": False}
    elif case == "wrapper":
        command = f"cd . && {OLD}"
    elif case == "other_requirement":
        goal["definition_of_done"].append(OLD)
    if case.endswith("_wrapper"):
        command = f"cd . && {OLD}"
    assert command not in method_provenance([command], goal, runtime)["revisable_commands"]


def test_generated_strategy_can_be_revised_only_after_real_failure_and_corrected_execution(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    store = JsonStore(context.validator)
    goal = generated_goal()
    task["verification_policy"]["method_provenance"] = method_provenance(
        [OLD, REQUIRED], goal, {
            "root_guidance": {"content": (tmp_path / "AGENTS.md").read_text(encoding="utf8"),
                              "truncated": False},
            "project_commands": store.read(context.asteria_dir / "project.json", "project_config")["commands"],
        },
    )
    store.write(context.run_dir / "goal_spec.json", goal, "goal_spec")
    store.write(context.run_dir / "task_plan.json", {"schema_version": "0.1.0", "tasks": [task]}, "task_board")
    before = deepcopy(goal)
    results = run_commands(task, context, gateway)
    assert not results[0].ok and results[1].ok
    prefix = (context.run_dir / "tool_observations.jsonl").read_bytes()
    result = gateway.run_tool_calls([
        {"tool_name": "revise_verification", "args": ARGS},
    ], task, context, stop_on_failure=False)[0]
    assert result.ok
    updated = store.read(context.run_dir / "task_plan.json", "task_board")["tasks"][0]
    assert updated["validation_commands"] == [NEW, REQUIRED]
    assert updated["verification_policy"]["method_revisions"][0]["failed_observation_id"]
    assert (context.run_dir / "tool_observations.jsonl").read_bytes().startswith(prefix)
    assert store.read(context.run_dir / "goal_spec.json", "goal_spec") == before
