import json
from pathlib import Path

import pytest

from asteria_runtime.core.budget import BudgetController, budget_evidence
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_budget_controller import policy


def test_evidence_uses_controller_limits_and_weighted_units_without_granting_budget():
    configured = policy(max_model_calls=2, max_tool_calls=2)
    configured.update(active_budget_profile="long", budget_profiles={
        "long": {"max_model_calls_per_goal": 30, "max_tool_calls_per_goal": 40},
    })
    budget = BudgetController(configured)
    for _ in range(5):
        budget.record_tool_call("read_file")
    budget.record_tool_call("write_file")
    configured["budget_profiles"]["long"]["max_model_calls_per_goal"] = 1
    evidence = budget_evidence(configured, budget.cost_report(), controller=budget)
    assert evidence["configured_limits"]["max_model_calls_per_goal"] == 30
    assert evidence["pressure"]["ratios"]["tool_budget_units"] == 2 / 40
    assert budget.cost_report()["tool_calls"] == 6
    assert budget.budgets["max_model_calls_per_goal"] == 30
    assert evidence["source"] == "budget_controller" and evidence["scope"] == "shared_goal"


@pytest.mark.parametrize("known", [True, False])
def test_worker_profile_records_shared_limits_not_role_call_count_or_tool_kinds(tmp_path, known):
    validator = SchemaValidator(Path("schemas"))
    configured = policy(max_model_calls=37, max_tool_calls=80) if known else {}
    context = RuntimeContext(tmp_path, "run-budget", configured, validator,
                             budget=BudgetController(configured) if known else None)
    mount = RuntimeProfileBuilder(validator).build_and_record(context=context,
        task={"task_id": "task-1", "role": "CoderAgent", "task_kind": "implementation",
              "allowed_tools": ["read_file"], "read_scope": [], "write_scope": []},
        worker_id="worker-1", runtime_context={})
    row = json.loads((context.run_dir / "runtime_profiles.jsonl").read_text(encoding="utf8"))
    assert row["budget"]["max_model_calls"] == (37 if known else None)
    assert row["budget"]["max_tool_calls"] == (80 if known else None)
    assert row["budget"]["tool_limit_unit"] == "weighted_tool_budget_units"
    assert "max_runtime_minutes" not in row["budget"]
    assert mount.runtime_context["agent_role_contract"]["provider_call_seconds"] > 0
    assert mount.runtime_context["runtime_budget"]["pressure"]["status"] == ("within_budget" if known else "unknown")
    validator.validate("runtime_profile", row)
